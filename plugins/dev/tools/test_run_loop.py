"""Tests for run_loop.RunLoop — the phased-plan loop as a state machine.

Sessions, git, kc's project list, and the deterministic test gate are faked:
each test scripts the sequence of (role, outcome) verdicts it expects the
driver to request — plus the gate's green/red sequence — and asserts on
transitions, caps, plan stamps, state.json, and bail-outs. No kc session is
created, no claude process is spawned, and no real suite runs.

Run: `python3 ${CLAUDE_PLUGIN_ROOT}/tools/test_run_loop.py` or via pytest.
"""

import contextlib
import fcntl
import importlib.util
import io
import itertools
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
import types
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

_spec = importlib.util.spec_from_file_location(
    "run_loop", Path(__file__).resolve().parent / "run_loop.py"
)
run_loop = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(run_loop)
# What `run_loop.run_kc_session` is before any test patches it
# (`ScriptedLoop.run` refuses to call it).
REAL_KC_SESSION = run_loop.run_kc_session
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

# The tool check reads the pod's running tool containers from `kc env
# describe`. The suite's pod is stubbed as running `python` alone; the tests
# of the check script their own (`running`).
RUNNING = {"python"}
REAL_RUNNING_TOOLS = run_loop.running_tools
run_loop.running_tools = lambda: set(RUNNING)
# The service check reads the pod's services from the same describe; the
# suite's pod runs none (as this environment's does), and no fixture's config
# declares one but the service tests' own.
RUNNING_SERVICES: set[str] = set()
REAL_RUNNING_SERVICES = run_loop.running_services
run_loop.running_services = lambda: set(RUNNING_SERVICES)
# Which repos kc marks shared comes from the same describe; the suite's
# environment shares none, and the tests of a shared repo's phase say which
# of theirs is.
REAL_SHARED_REPO_DIRS = run_loop.shared_repo_dirs
run_loop.shared_repo_dirs = lambda: set()
# So do the repos config.yaml declares, asked when a repo-path Target is
# missing; the suite's environment declares none, so a missing Target reads
# as a wrong path, and the tests of one not cloned yet say which it is.
REAL_DECLARED_REPO_DIRS = run_loop.declared_repo_dirs
run_loop.declared_repo_dirs = lambda: {}
# A shared repo's phase works in a worktree under WORKTREE_ROOT. Never the
# pod's own scratch root from the suite: the scripted loops point it into
# their test's tmp dir for the run (`ScriptedLoop.run`), and this is the
# floor under any call that goes round them.
run_loop.WORKTREE_ROOT = (Path(tempfile.gettempdir())
                          / "aiworkflow-suite-worktrees")

# spawn_flags copies the promoted MCP servers out of the user-level
# ~/.claude.json. That seam is stubbed with a home that does not exist, so no
# test reads or writes the operator's own files; nothing is promoted and the
# flags are the bare trim. The tests that exercise the promotion point the
# seam at a throwaway home of their own (`promoted_home`).
NO_HOME = Path(tempfile.gettempdir()) / "aiworkflow-suite-no-home"
run_loop._user_home = lambda: NO_HOME

# The version guard reads Claude Code's installed_plugins.json, which on the
# machine running the suite names whatever is installed there — not this
# tree's version. Pointed at a file that does not exist, the guard fails open;
# the tests that exercise it write their own (`installed`).
run_loop.INSTALLED_PLUGINS = NO_HOME / "installed_plugins.json"

# Pilot's halt file is the host's (`/work/...`): a pod running the suite while
# a halt holds would halt every run in it. Pointed at a file that does not
# exist; the tests of the halt make one of their own (`halt_file`).
run_loop.HALT_FILE = NO_HOME / "quota-limit-halt-requested"


class FakeGit:
    """Answers the git queries the driver makes; records mutations. The
    driver roots calls per target repo via the `root=` kwarg; the fake
    records it so cross-repo tests can assert where a mutation landed."""

    def __init__(self, spec_root=""):
        self.calls = []          # (root, args)
        self.branches = set()
        self.head = "abc123"
        self.revs = {}           # ref → its sha, overriding `head`
        # `rev-parse <ref>^{tree}`: ref → its tree. A ref not in it has a
        # tree of its own, so a phase's range is not empty unless a test
        # gives its base and HEAD the same tree.
        self.trees = {}
        self.spec_root = spec_root   # what `rev-parse --show-toplevel` says
        # str(root) → what `rev-parse --show-toplevel` says there instead —
        # a ledger's clone ("" for a directory that is no checkout).
        self.toplevels = {}
        self.branch = "main"     # the branch every root is checked out on
        self.branch_at = {}      # str(root) → its branch, overriding `branch`
        self.diff_files = ""     # what `diff --name-only` reports
        self.stat = ""           # what `diff --stat` reports
        self.stats = {}          # "<base>..<head>" → its stat, over `stat`
        self.diff = ""           # what a plain `diff <range>` reports
        self.diffs = []          # plain-diff answers, consumed in order first
        # What `git_raw("show", "<rev>:<path>")` reads — (rev, path) → the
        # blob's text; a pair not in it is refused, as git refuses a path
        # its commit does not have.
        self.blobs = {}
        self.merge_bases = []    # `merge-base` answers, consumed in order
        self.merge_base = "base123"   # the answer once `merge_bases` is spent
        # What `merge_base` becomes once `rebase` ran, when set: the branch
        # rebased onto its moved base has a merge base of its own.
        self.rebased_merge_base = None
        self.dirty = ""          # what `status --porcelain` reports
        self.dirty_roots = {}    # str(root) → porcelain, overriding `dirty`
        self.branch_files = ""   # what `log --name-only` and `ls-tree` report
        self.unpushed = {}       # str(root) → `rev-list --count` answer
        self.no_origin = set()   # roots where `origin/<base>` does not exist
        # What `rev-parse --verify` answers for a fully qualified
        # `refs/remotes/…` ref — the one the base sync and the origin-ahead
        # line read. Absent is no such ref: no base moves and no dispatch
        # says origin is ahead (the real-git tests cover both).
        self.remote_refs = {}
        self.ahead = {}          # "<base>..<branch>" → commits it is ahead by
        self.lost = set()        # shas no ref in this repo reaches any more
        self.merged = set()      # shas the base branch carries
        self.rebased_head = None  # sha `rebase` moves HEAD to, when set
        self.fails = set()       # argv tuples this git refuses, as git does
        self.not_in = set()      # (sha-or-ref, ref) ancestry answered no
        self.commits = 0         # pathspec commits made through `root=`
        # A per-repo ref model, opt-in per root (the wrap-up's tests): the
        # branches of that repo with their shas, and a commit graph that
        # `rev-list --count` walks. A root not in `refs` answers as above.
        self.refs = {}           # str(root) → {ref: sha}
        # sha → its parent; in any repo, also what `rev-parse --verify
        # <sha>^` answers (none: a root commit).
        self.parents = {}
        # The spec repo as `git -C <slice dir>` sees it: its HEAD, the text
        # each path had at the last commit through it, and the store as it
        # stood each time HEAD was read — what `show <sha>:` answers.
        self.spec_head = "spec0"
        self.specs_committed = {}
        self.spec_snapshots = {}
        self.specs_commits = []   # the messages, in order
        # A shared repo's phase worktrees: path → branch, made on disk by
        # `worktree add` (a `.git` file, so the driver finds one there, and
        # the repo's kc manifest, as a checkout of its base carries it — the
        # gate reads it in the phase's tree) and gone at `worktree remove`;
        # the lock reason of each add; what
        # `worktree list --porcelain` answers; and the answers of the git
        # commands the driver reads rather than bails on (`_git_attempt`),
        # consumed in order — (0, "Fast-forward") once spent.
        self.worktrees = {}
        self.lock_reasons = []
        self.worktree_list = ""
        self.attempts = []
        # What a resume sets aside from a dirty tree: str(root) → the text
        # `diff --output=<file>` writes there, and → the paths `ls-files
        # --others` lists (the files themselves are the test's to make).
        self.uncommitted = {}
        self.untracked = {}

    def __call__(self, *args, root=None, check=True):
        self.calls.append((root, args))
        if args in self.fails:
            if check:
                raise Bailout("protocol_failure",
                              details=f"git {' '.join(args)} failed")
            return ""
        if args and args[0] == "-C":
            answer = self._spec(args[1], args[2:])
            if answer is not None:
                return answer
        refs = self.refs.get(str(root))
        if refs is not None:
            answer = self._modelled(refs, args, str(root))
            if answer is not None:
                return answer
        if args[:3] == ("rev-parse", "--abbrev-ref", "HEAD"):
            return self.branch_at.get(str(root), self.branch)
        if args[:2] == ("rev-parse", "--show-toplevel"):
            return self.toplevels.get(str(root), self.spec_root)
        if args[0] == "diff" and any(a.startswith("--output=") for a in args):
            out = next(a for a in args if a.startswith("--output="))
            Path(out.removeprefix("--output=")).write_text(
                self.uncommitted.get(str(root), ""))
            return ""
        if args[:2] == ("ls-files", "--others"):
            return "".join(f"{p}\0" for p in self.untracked.get(str(root), ()))
        if args[0] == "diff" and "--name-only" in args:
            return self.diff_files
        if args[0] == "diff" and any(a.startswith("--stat") for a in args):
            rng = next((a for a in args if ".." in a), None)
            return self.stats.get(rng, self.stat)
        if args[0] == "diff":
            return self.diffs.pop(0) if self.diffs else self.diff
        if args[0] == "rev-list":
            if args[-1].startswith("origin/"):
                return self.unpushed.get(str(root), "0")
            return self.ahead.get(args[-1], "0")
        if args[:2] == ("rev-parse", "--verify") \
                and args[-1].startswith("refs/remotes/"):
            return self.remote_refs.get(args[-1], "")
        if args[:2] == ("rev-parse", "--verify") \
                and args[-1].endswith("^{commit}"):
            rev = args[-1].removesuffix("^{commit}")
            return self.revs.get(rev, rev)
        if args[:2] == ("rev-parse", "--verify") and args[-1].endswith("^"):
            return self.parents.get(args[-1].removesuffix("^"), "")
        if args[:2] == ("rev-parse", "--verify"):
            return "" if str(root) in self.no_origin else self.head
        if args[0] == "rev-parse" and args[-1].endswith("^{tree}"):
            ref = args[-1].removesuffix("^{tree}")
            return self.trees.get(ref, f"tree-{ref}")
        if args[0] == "rev-parse":
            return self.revs.get(args[-1], self.head)
        if args[0] == "merge-base":
            return (self.merge_bases.pop(0) if self.merge_bases
                    else self.merge_base)
        if args[0] in ("log", "ls-tree"):
            return self.branch_files
        if args[0] == "status":
            return self._status(args, root)
        if args[0] == "branch" and args[1] == "--list":
            return args[2] if args[2] in self.branches else ""
        if args[0] == "checkout" and args[1] == "-b":
            self.branches.add(args[2])
            self.branch_at[str(root)] = args[2]
            return ""
        if args[0] == "checkout":
            self.branch_at[str(root)] = args[1]
            return ""
        if args[0] == "branch" and args[1] == "-D":
            self.branches.discard(args[2])
            return ""
        if args[0] == "rebase" and args[1] != "--abort" and self.rebased_head:
            self.head = self.rebased_head
            if self.rebased_merge_base:
                self.merge_base = self.rebased_merge_base
            return ""
        if args[0] == "commit" and "--" in args:
            self._commit_paths(args, root)
            return ""
        if args[:2] == ("worktree", "add"):
            return self._worktree_add(args[2:], root)
        if args[:2] == ("worktree", "list"):
            return self.worktree_list
        return ""

    def _worktree_add(self, rest, root=None):
        rest = [a for a in rest if a != "--lock"]
        if "--reason" in rest:
            i = rest.index("--reason")
            self.lock_reasons.append(rest[i + 1])
            del rest[i:i + 2]
        path = Path(rest[0])
        branch = rest[2] if rest[1] == "-b" else rest[1]
        if rest[1] == "-b":
            self.branches.add(branch)
        path.mkdir(parents=True, exist_ok=True)
        (path / ".git").write_text("gitdir: a fake's\n")
        manifest = Path(root or "") / run_loop.MANIFEST_REL
        if root is not None and manifest.is_file():
            (path / run_loop.MANIFEST_REL).parent.mkdir(exist_ok=True)
            shutil.copyfile(manifest, path / run_loop.MANIFEST_REL)
        self.branch_at[str(path)] = branch
        self.worktrees[str(path)] = branch
        return ""

    def _spec(self, where, args):
        if args[:2] == ("rev-parse", "HEAD"):
            store = Path(where) / "close-out.json"
            if store.exists():
                self.spec_snapshots[self.spec_head] = store.read_text()
            return self.spec_head
        if args[0] == "show":
            sha = args[1].partition(":")[0]
            return self.spec_snapshots.get(sha, "").strip()
        if args[0] == "status" and "--" in args:
            paths = args[args.index("--") + 1:]
            return "\n".join(
                f" M {path}" for path in paths if Path(path).exists()
                and Path(path).read_text() != self.specs_committed.get(path))
        if args[0] == "commit" and "--" in args:
            for path in args[args.index("--") + 1:]:
                if Path(path).exists():
                    self.specs_committed[path] = Path(path).read_text()
            self.specs_commits.append(args[args.index("-m") + 1])
            self.spec_head = f"spec{len(self.specs_commits)}"
            return ""
        return None

    def _ancestors(self, sha):
        seen = set()
        while sha and sha not in seen:
            seen.add(sha)
            sha = self.parents.get(sha)
        return seen

    def _modelled(self, refs, args, key):
        cur = self.branch_at.get(key, self.branch)

        def resolve(name):
            return refs.get(cur if name == "HEAD" else name, name)

        if args[0] == "rev-parse" and len(args) == 2 \
                and not args[1].startswith("-"):
            return resolve(args[1])
        if args[:2] == ("branch", "--list"):
            return args[2] if args[2] in refs else ""
        if args[:2] == ("checkout", "-b"):
            refs[args[2]] = resolve(args[3] if len(args) > 3 else "HEAD")
            self.branch_at[key] = args[2]
            return ""
        if args[0] == "checkout" and len(args) == 2:
            self.branch_at[key] = args[1]
            return ""
        if args[:2] == ("branch", "-D"):
            refs.pop(args[2], None)
            return ""
        if args[:2] == ("branch", "-f"):
            refs[args[2]] = resolve(args[3])
            return ""
        if args[:2] == ("merge", "--ff-only"):
            refs[cur] = resolve(args[2])
            return ""
        if args[:2] == ("reset", "--hard"):
            if len(args) > 2 and args[2] != "HEAD":
                refs[cur] = resolve(args[2])
            self.dirty_roots[key] = ""
            return ""
        if args[0] in ("clean", "restore"):
            self.dirty_roots[key] = ""
            return ""
        if args[:2] == ("rev-list", "--count"):
            low, _, high = args[2].partition("..")
            return str(len(self._ancestors(resolve(high))
                           - self._ancestors(resolve(low))))
        if args[:2] == ("push", "origin"):
            refs[f"origin/{args[2]}"] = resolve(args[2])
            return ""
        if args[0] in ("rebase", "fetch"):
            return ""
        return None

    def commit_on(self, root, ref, sha):
        """A commit `sha` on `ref` in a modelled repo."""
        refs = self.refs[str(root)]
        self.parents[sha] = refs[ref]
        refs[ref] = sha

    @staticmethod
    def _under(path, spec):
        return path == spec or path.startswith(spec + "/")

    def _status(self, args, root):
        """Porcelain, honouring `:(exclude)<dir>` — the pathspec the driver
        holds its own bookkeeping out with when the target repo holds the
        slice folder — a plain `<dir>` pathspec, and `--untracked-files=no`."""
        text = self.dirty_roots.get(str(root), self.dirty)
        excluded = [a[len(":(exclude)"):] for a in args
                    if a.startswith(":(exclude)")]
        tail = args[args.index("--") + 1:] if "--" in args else ()
        included = [a for a in tail if not a.startswith(":(") and a != "."]
        return "\n".join(
            line for line in text.splitlines()
            if not any(self._under(line[3:], x) for x in excluded)
            and (not included
                 or any(self._under(line[3:], x) for x in included))
            and not ("--untracked-files=no" in args
                     and line.startswith("??")))

    def _commit_paths(self, args, root):
        """`commit … -- <dir> [:(exclude)<path>…]`: the tracked changes the
        pathspec matches are committed — the untracked stay dirty, and so
        does everything outside it — and HEAD moves to a new commit."""
        tail = args[args.index("--") + 1:]
        excluded = [a[len(":(exclude)"):] for a in tail
                    if a.startswith(":(exclude)")]
        included = [a for a in tail if not a.startswith(":(")]

        def committed(path):
            return (any(self._under(path, x) for x in included)
                    and not any(self._under(path, x) for x in excluded))

        key = str(root)
        text = self.dirty_roots.get(key, self.dirty)
        kept = "\n".join(line for line in text.splitlines()
                         if line.startswith("??") or not committed(line[3:]))
        if key in self.dirty_roots:
            self.dirty_roots[key] = kept
        else:
            self.dirty = kept
        self.commits += 1
        self.head = f"slicecommit{self.commits}"

    def ok(self, *args, root=None):
        """`git_ok` — the queries answered by an exit status. A recorded
        commit is on its phase branch unless the test says it was lost, and
        in the base branch only when the test says it merged."""
        self.calls.append((root, args))
        if args[:2] == ("merge-base", "--is-ancestor"):
            sha, ref = args[2], args[3]
            if (sha, ref) in self.not_in:
                return False
            if ref.startswith("phase/"):
                return sha not in self.lost
            return sha in self.merged
        if args[:2] == ("worktree", "remove"):
            shutil.rmtree(args[-1], ignore_errors=True)
            self.worktrees.pop(args[-1], None)
        return True

    def raw(self, *args, root=None, check=True):
        """`git_raw` — a blob from `blobs` for `show <rev>:<path>`; anything
        else (the diffs the redactor reads) as `__call__` answers it."""
        if args and args[0] == "show":
            self.calls.append((root, args))
            rev, _, path = args[1].partition(":")
            if (rev, path) not in self.blobs or args in self.fails:
                raise Bailout("protocol_failure",
                              details=f"git {' '.join(args)} failed:\n"
                                      f"fatal: path '{path}' does not exist "
                                      f"in '{rev}'")
            return self.blobs[(rev, path)]
        return self(*args, root=root, check=check)

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
                 doc_gates=None, repo_root=None, sweep_reds=None,
                 wrap_ups=None, wrap_gates=None, setup_rcs=None):
        super().__init__(Path(slice_dir), resume=resume)
        if repo_root is not None:
            self.repo_root = Path(repo_root)
        self.script = list(script)
        self.spawned = []    # (role, phase, round, outcome)
        self.prompts = []    # (role, prompt)
        self.gates = list(gates or [])
        self.gate_calls = []
        self.gate_merge_bases = []   # the review range's base each gate took
        self.doc_gates = list(doc_gates or [])
        self.doc_gate_calls = []
        self.sweep_reds = set(sweep_reds or [])   # (component, verb) → red
        self.sweep_calls = []                     # (root, component, verb)
        self.fake_git = FakeGit(
            spec_root=str(run_loop.spec_root_for(self.slice_dir) or ""))
        self.git = self.fake_git
        self.git_ok = self.fake_git.ok
        self.git_raw = self.fake_git.raw
        self.sleeps = []
        self.gate_cwds = []   # where each scripted gate ran
        # A shared repo's phase worktrees go under the test's own tmp dir.
        spec_root = run_loop.spec_root_for(self.slice_dir)
        self.worktree_root = ((spec_root.parent if spec_root
                               else self.slice_dir) / "scratch" / "worktrees")
        # The wrap-up is dispatched through a path of its own, straight to
        # `run_kc_session` — never `_spawn` — so its sessions are faked at
        # that seam (`run`): a script of (payload[, effect]) steps, and a
        # wrap-up nobody scripted answers `done` having done nothing.
        self.wrap_ups = list(wrap_ups or [])
        self.wrap_up_sessions = []
        self.wrap_gates = list(wrap_gates or [])   # the wrap-up gate: green?
        self.wrap_gate_calls = []                  # (argv, cwd)
        # The run-start `kc project setup`: an exit code or an exception to
        # raise per run, in order (0 once spent).
        self.setup_rcs = list(setup_rcs or [])
        self.setup_runs = []                       # (argv, cwd, spawns so far)

    def run(self):
        outer = run_loop.run_kc_session

        def route(prompt, cwd, timeout, agent=None, **kw):
            if agent == "wrap-up":
                return self._wrap_up_session(prompt, cwd, timeout,
                                             agent=agent, **kw)
            # No loop under test reaches the real thing: a dispatch path
            # that goes round `_spawn` and that no test faked would start an
            # agent from the suite.
            assert outer is not REAL_KC_SESSION, (
                f"a test reached the real run_kc_session (agent {agent!r})")
            return outer(prompt, cwd, timeout, agent=agent, **kw)

        with patched(run_loop, run_kc_session=route,
                     WORKTREE_ROOT=self.worktree_root):
            return super().run()

    def _wrap_up_session(self, prompt, cwd, timeout, agent=None, model=None,
                         effort=None, resume_session=None, extra_env=None,
                         flags=None, progress=None, on_session=None):
        step = (self.wrap_ups.pop(0) if self.wrap_ups
                else ({"outcome": "done", "summary": "nothing to do"},))
        payload = step[0]
        self.wrap_up_sessions.append({
            "prompt": prompt, "cwd": cwd, "timeout": timeout, "agent": agent,
            "model": model, "effort": effort, "flags": list(flags or ()),
            "resume": resume_session, "env": dict(extra_env or {})})
        result = run_loop.SessionResult()
        result.session_id = f"sess-wrap-{len(self.wrap_up_sessions)}"
        if on_session:
            on_session(result.session_id)
        # what the session did on disk, whatever it answered after
        if len(step) > 1:
            step[1](self)
        verdict_path = self.slice_dir / "wrap_up_result.json"
        if payload is TIMED_OUT:
            raise subprocess.TimeoutExpired("kc", timeout)
        if isinstance(payload, tuple) and payload[0] is TIMED_OUT:
            verdict_path.write_text(json.dumps(payload[1]))
            raise subprocess.TimeoutExpired("kc", timeout)
        if isinstance(payload, str):
            result.result_text = payload
            return 1, result
        verdict_path.write_text(json.dumps(payload))
        result.result_text = payload.get("summary") or "verdict written"
        return 0, result

    def _wrap_up_gate_exec(self, argv, cwd, log_file):
        green = self.wrap_gates.pop(0) if self.wrap_gates else True
        self.wrap_gate_calls.append((list(argv), str(cwd)))
        log_file.write("wrap-up gate output\n")
        return 0 if green else 1

    def _setup_exec(self, argv, cwd, log_file):
        self.setup_runs.append((list(argv), Path(cwd), len(self.spawned)))
        rc_ = self.setup_rcs.pop(0) if self.setup_rcs else 0
        if isinstance(rc_, BaseException):
            raise rc_
        log_file.write(f"{' '.join(argv)}: exit {rc_}\n")
        return rc_

    def _sleep(self, seconds):
        self.sleeps.append(seconds)

    def _assert_agents(self):
        pass  # the real assertion has its own unit test

    def _git_attempt(self, *args, root):
        self.git(*args, root=root, check=False)
        return (self.fake_git.attempts.pop(0) if self.fake_git.attempts
                else (0, "Fast-forward"))

    def _run_gate(self, phase_id, ps, outputs, target, merge_base):
        if target.gate_argv is None:
            return True, None
        self.gate_merge_bases.append(merge_base)
        ps["gate_runs"] += 1
        green = self.gates.pop(0) if self.gates else True
        self.gate_calls.append((phase_id, green))
        self.gate_cwds.append(Path(target.gate_cwd))
        log_path = outputs / f"gate_r{ps['gate_runs']}.log"
        log_path.write_text("gate output\n")
        if green:
            ps["gate_green_commit"] = self.git("rev-parse", "HEAD",
                                               root=target.work_root)
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

    def _run_sweep_cmd(self, root, component, verb, out_dir,
                       component_dir=None):
        green = (component, verb) not in self.sweep_reds
        self.sweep_calls.append((str(root), component, verb))
        log_path = out_dir / f"{root.name}_{component}_{verb}.log"
        log_path.write_text("sweep output\n")
        return {"repo": str(root), "component": component, "verb": verb,
                "outcome": "green" if green else "red", "green": green,
                "log": str(log_path), "duration_s": 0}

    def _spawn(self, role, prompt, cwd, verdict_path, phase_id, round_,
               agent=None, display=None):
        # The real _spawn's preamble, kept in step so the scripted loop
        # exercises the resume's stop entries, the salvage of an interrupted
        # round, and the spec tree's base assertion.
        self._report_bailouts()
        verdict_path = Path(verdict_path)
        salvaged = self._salvage_reattach(role, phase_id, verdict_path, "[t]")
        if salvaged is not None:
            verdict, session = salvaged
            self._record(phase_id, role, round_, verdict["outcome"],
                         verdict.get("summary", ""), session, 0)
            return verdict, session
        self._assert_spec_on_base()
        self._assert_current()
        prompt, resume_session = self._resolve_reattach(
            role, phase_id, prompt, verdict_path, "[t]")
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
    (role, text) for a session that produced only that text and no verdict.
    A nudge consumes a step of its own; answer it with SWALLOWED (or "") for
    a send the harness ate for its stopped-task recovery — which, for a
    verdict nudge, buys a mid-wait recovery resume of the same session."""

    def __init__(self, slice_dir, script, **kw):
        super().__init__(slice_dir, script, **kw)
        self.sessions = []
        self.session_prompts = []
        self.session_flags = []
        self.session_resumes = []   # (role, resume_session, timeout)
        self.session_envs = []      # (role, extra_env)
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
        self.session_resumes.append((role, resume_session, timeout))
        self.session_envs.append((role, dict(extra_env or {})))
        result = run_loop.SessionResult()
        result.session_id = f"sess-{len(self.sessions)}"
        if on_session:
            on_session(result.session_id)
        if payload is TIMED_OUT:
            raise subprocess.TimeoutExpired("kc", timeout)
        if isinstance(payload, tuple) and payload[0] is TIMED_OUT:
            verdict_path.write_text(json.dumps(payload[1]))
            raise subprocess.TimeoutExpired("kc", timeout)
        if isinstance(payload, tuple) and payload[0] is EXITED:
            _, returncode, verdict = payload
            verdict_path.write_text(json.dumps(verdict))
            result.result_text = verdict.get("summary") or "verdict written"
        elif isinstance(payload, str):
            result.result_text = payload
            returncode = 1
        else:
            verdict_path.write_text(json.dumps(payload))
            # A real turn always answers with something; an empty response is
            # the harness's no-op, so the default here is never empty.
            result.result_text = payload.get("summary") or "verdict written"
            returncode = 0
        # The effect runs either way: what a session left on disk is as much
        # a fact about one that wrote no verdict as about one that did.
        if len(step) > 2:
            step[2](self)
        return returncode, result


SESSION_LIMIT_TEXT = ("You've hit your session limit · resets 10:10pm "
                      "(Europe/Amsterdam)")
TIMED_OUT = object()   # a script step whose session never returns
EXITED = object()      # a script step whose session returns a chosen rc
# The CLI's stopped-task recovery answering a resume in the model's place.
SWALLOWED = "No response requested."


def timed_out_after(verdict):
    """A script step whose session wrote its verdict and *then* wedged: the
    turn never returns, but the work and the verdict are already on disk."""
    return (TIMED_OUT, verdict)


def exited_with(returncode, verdict):
    """A script step whose session wrote its verdict and then died on a
    non-zero exit — a SIGTERM'd worker, a send the harness lost after the
    turn."""
    return (EXITED, returncode, verdict)


def dirties(porcelain=" M src/app.py"):
    """A script step's effect: the session left uncommitted work behind."""
    def effect(loop):
        loop.fake_git.dirty = porcelain
    return effect


def commits(loop):
    """A script step's effect: the session committed — the tree is clean."""
    loop.fake_git.dirty = ""


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
    # The spec tree's lease lives in its git dir, so the real lock runs in
    # the suite — over tmp files, with real flock.
    (root / "specs" / ".git").mkdir(exist_ok=True)
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
    """What the run's render wrote: the document Pilot reads, where there is
    an ask, then the record."""
    return "".join((slice_dir / name).read_text()
                   for name in ("close-out.md", "close-out-record.md")
                   if (slice_dir / name).exists())


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


class promoted_home(patched):
    """Point the promoted-MCP read and write at a throwaway home and drop the
    per-process flag cache on the way in and out, so one test's answer never
    becomes the next one's."""

    def __init__(self, home, claude_json=None):
        self.home = Path(home)
        self.home.mkdir(parents=True, exist_ok=True)
        if claude_json is not None:
            (self.home / run_loop.USER_CLAUDE_JSON).write_text(claude_json)
        super().__init__(run_loop, _user_home=lambda: self.home)

    @property
    def config_path(self):
        return self.home / run_loop.PROMOTED_MCP_FILE

    def __enter__(self):
        run_loop._PROMOTED_MCP.clear()
        return super().__enter__()

    def __exit__(self, *exc):
        run_loop._PROMOTED_MCP.clear()
        return super().__exit__(*exc)


# An invented ~/.claude.json: the promoted servers (fieldnotes with a bearer
# token, gitblit with none, the KubeCoder worker with the session header kc
# writes, as on the host), one that must not travel, and the rest of the
# file's top-level keys the copy must ignore.
FAKE_CLAUDE_JSON = json.dumps({
    "numStartups": 12,
    "mcpServers": {
        "fieldnotes": {"type": "http", "url": "https://fieldnotes.invalid/mcp",
                       "headers": {"Authorization": "Bearer sekrit-token"}},
        "gitblit": {"type": "http", "url": "http://git/api/mcp/mcp"},
        "kubecoder-worker": {
            "type": "http", "url": "http://127.0.0.1:44557/mcp",
            "headers": {"X-Kubecoder-Session-Name": "${KUBECODER_SESSION_NAME:-}"}},
        "jenkins": {"type": "http", "url": "https://jenkins.invalid/mcp"},
    },
    "projects": {"/work/app": {"mcpServers": {"fieldnotes": {"type": "sse"}}}},
})


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
        # creation, its store staged by name too
        specs = r.fake_git.specs_ops()
        adds = [c for c in specs if c[2] == "add"]
        commits = [c for c in specs if c[2] == "commit"]
        assert [[Path(a).name for a in c[3:]] for c in adds] == \
            [["close-out.json"], ["plan.md"], ["plan.md"]]
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
    and what earlier phases changed — one `--stat` per merged phase, over
    that phase's own landed range in the repo it landed in."""
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
        # an earlier phase landed in a sibling repo too — P1 is stamped done
        # in the plan, so the loop never creates its record and the merged
        # record is seeded at the first digest instead
        orig = r._phase_digest

        def seeded(phase_id):
            if "1" not in r.state["phases"]:
                r._phase_state("1").update(
                    status="merged",
                    landed={"root": "/elsewhere/Sibling", "base": "s1b",
                            "head": "s1h"})
            return orig(phase_id)
        r._phase_digest = seeded
        assert run_to_exit(r) == 0
        writers = [p for role, p in r.prompts if role == "code-writer"]
        first, fix, third = writers[0], writers[1], writers[2]
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
            assert "P1 in /elsewhere/Sibling:" in prompt
        assert "digested below" in fix
        # P3's writer sees P2's landed range, in the repo P2 landed in
        assert f"P2 in {repo}:" in third
        stats = [(root, c) for root, c in r.fake_git.calls
                 if c[0] == "diff" and c[1].startswith("--stat")]
        assert (Path("/elsewhere/Sibling"),
                ("diff", "--stat=100", "s1b..s1h")) in stats
        assert (repo, ("diff", "--stat=100", "base123..abc123")) in stats
        # never the base branch since the slice began
        assert not [c for _, c in stats
                    if c[2].endswith(("..main", "..base123"))]


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
    # A frontmatter block above the title is skipped, blank lines around it
    # included; an opener with no closer is not frontmatter.
    assert run_loop.slice_intent(
        "---\nissue: KC-1201\n---\n# T\n\nFirst para.\n\nSecond.\n") \
        == "First para."
    assert run_loop.slice_intent(
        "---\nissue: KC-1201\n---\n\n\n# T\n\nFirst para.\n") == "First para."
    assert run_loop.slice_intent(
        "---\nissue: KC-1201\n\n# T\n\nFirst para.\n") == "---\nissue: KC-1201"
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


DONE_RECORD_TWO_PART = (
    "Plan text for P1.\n\n"
    "**Done (P1).** Landed the seam in `x.py`,\n"
    "gate green on the second round.\n\n"
    "Later phases:\n"
    "- the seam is `x.py`, call it from your handler\n"
    "- the fixture is owed: P4 writes it\n\n"
    "- **Round 2 (F1):** the story.\n\n"
    "Gate: kc project test OK, 240 tests\n")


def test_phase_digest_carries_the_done_record_summary():
    """The writer's per-phase digest takes each earlier record's summary —
    its opener paragraph plus the `Later phases:` list — not the phase's own
    story (rounds, witnessed reds, the gate line). A record with no such
    block, and a done phase with no opener at all, are carried whole; the
    doc phase's whole-plan digest still gets every record entire."""
    plan = "\n".join([
        "# Slice 9 — The summary", "",
        "## Phases", "",
        phase_section("1", "Groundwork", done=True, body=DONE_RECORD_TWO_PART),
        phase_section("2", "Bare", done=True,
                      body="**Done (P2).** Bare.\n\nGate: OK\n"),
        phase_section("3", "No opener", done=True, body="Only plan text.\n"),
        phase_section("4", "Mine", body="Do this.\n")])
    digest = run_loop.build_phase_digest(plan, "4", "", [], [])
    assert "## Settled by earlier phases (their done-record summaries)" in digest
    # P1: the opener paragraph and the whole `Later phases:` list
    assert "**Done (P1).** Landed the seam in `x.py`,\n" \
           "gate green on the second round." in digest
    assert "Later phases:" in digest
    assert "- the seam is `x.py`, call it from your handler" in digest
    assert "- the fixture is owed: P4 writes it" in digest
    # …and none of the phase's own story behind it
    assert "the story." not in digest
    assert "240 tests" not in digest
    assert "Plan text for P1." not in digest
    # P2: an opener with no block — the record whole
    assert "**Done (P2).** Bare." in digest and "Gate: OK" in digest
    # P3: no opener at all — its whole section
    assert "Only plan text." in digest
    # the doc phase reads the records entire
    assert "the story." in run_loop.build_slice_digest(plan)

    phases, _ = run_loop.parse_plan(plan)
    by_id = {p.id: p for p in phases}
    assert run_loop.done_record_summary(by_id["1"]) == [
        "**Done (P1).** Landed the seam in `x.py`,",
        "gate green on the second round.",
        "",
        "Later phases:",
        "- the seam is `x.py`, call it from your handler",
        "- the fixture is owed: P4 writes it",
    ]
    assert run_loop.done_record_summary(by_id["2"]) is None
    assert run_loop.done_record_summary(by_id["3"]) is None
    assert run_loop.records_without_summary(plan, "4") == ["2", "3"]
    assert run_loop.records_without_summary(plan, "2") == []


def test_done_record_summary_takes_the_marker_bold_or_plain():
    """`Later phases:` is recognised bolded, as the writers emit it."""
    plan = "\n".join([
        "# Slice 9 — Bold", "", "## Phases", "",
        phase_section("1", "Groundwork", done=True,
                      body="**Done (P1).** Landed.\n\n"
                           "**Later phases:**\n- use the seam.\n\n"
                           "Gate: OK\n"),
        phase_section("2", "Mine", body="Do this.\n")])
    phases, _ = run_loop.parse_plan(plan)
    assert run_loop.done_record_summary(phases[0]) == [
        "**Done (P1).** Landed.", "", "**Later phases:**", "- use the seam."]
    assert run_loop.records_without_summary(plan, "2") == []


def test_phase_digest_logs_a_record_it_could_not_summarise():
    """The driver says in log.txt which earlier record rode the digest whole
    — a run whose writers wrote records off-shape leaves a trail."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp, phases=[
            phase_section("1", "Groundwork", done=True,
                          body="**Done (P1).** Laid; no block behind it.\n"),
            ("2", "The feature"),
        ])
        r = ScriptedLoop(slice_dir,
                         [V["exec_done"], V["review_signoff"], *TAIL],
                         repo_root=repo)
        assert run_to_exit(r) == 0
        assert ("[P2] digest: P1's done-record has no 'Later phases:' block "
                "— carried whole") in (slice_dir / "log.txt").read_text()
        prompt = next(p for role, p in r.prompts if role == "code-writer")
        assert "**Done (P1).** Laid; no block behind it." in prompt


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
        flat = prompt.replace("\n", " ")
        # a gate on record with no lint claims none (AIWF-105)
        assert ("The tests pass; that is an established input to your review, "
                "not something to re-derive. Do not re-run the suite to "
                "confirm it.") in flat
        assert "vacuous" in prompt
        assert "lint" not in run_loop.GATE_UNVERIFIED_LINE
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


def test_gate_line_names_its_repo_and_a_review_sets_untested_clones():
    """The gate paragraph says where the gate ran; with a review set outside
    the Target it closes on the driver having run no suite in its clones —
    whichever paragraph it is (AIWF-37)."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r = ScriptedLoop(slice_dir, [], repo_root=repo)
        target = run_loop.ResolvedTarget(
            PROJECT, "project", Path(repo),
            ["kc", "project", "test", "--project", PROJECT], Path(repo))
        green = {"gate_green_commit": "deadbeefcafe0",
                 "gate_green_log": "/g/gate_r1.log"}
        line = r._gate_line(green, "deadbeefcafe0", target)
        assert (f"`kc project test --project {PROJECT}` in {repo} — with "
                "full output in /g/gate_r1.log") in line.replace("\n", " ")
        assert "suite alone" not in line
        clones = ["/work/scratch/A", "/work/scratch/B"]
        line = r._gate_line(green, "deadbeefcafe0", target, clones)
        assert "ran GREEN on this exact commit" in line
        assert (f"That gate is {repo}'s suite alone: the driver ran no suite "
                "in the review set's repos (/work/scratch/A, "
                "/work/scratch/B)") in line.replace("\n", " ")
        assert "unverified by the driver" in line.replace("\n", " ")
        assert r._gate_line({}, "abc123", target, clones).startswith(
            run_loop.GATE_UNVERIFIED_LINE + "\nThat gate is")
        nothing = {"gate_nothing_ran_commit": "deadbeefcafe0"}
        assert f"` in {repo} ran nothing" in r._gate_line(
            nothing, "deadbeefcafe0", target)


# -- the review set: a phase's work outside its Target (AIWF-37) ---------------
#
# Ansible slice 036 (Target: root) committed its work into thirteen
# /work/scratch clones, listed in a ledger beside the plan; its reviewer was
# handed root's empty range and a GREEN about a suite the phase never touched.

SHA_A = "96ab9a82da98465b6f89cee67412a30e0349f7b9"
SHA_B = "4e533de1d8e74481acc40f8b0f9a0f5c71cbcbf2"
SHA_B2 = "2583334f61ee250bc55324a44ff0a671f0ee3afc"
SHA_C = "b353012c2b5f597d8f711cacf7d4c3d27f9b3de9"


def ledger(*rows):
    """A ledger in slice 036's shape: prose, then a table row per file —
    (repo, clone, sha)."""
    lines = ["# Migration ledger", "",
             "The push list for the repos the run does not track "
             "([consumer files](attachments/consumer-files.md)).", "",
             "| Repo | Job | Clone | Branch | File | Commit |",
             "| --- | --- | --- | --- | --- | --- |"]
    lines += [f"| {repo} | Jobs/{repo} | `{clone}` | `main` | `Jenkinsfile` "
              f"| `{sha}` |" for repo, clone, sha in rows]
    return "\n".join(lines) + "\n"


def test_review_set_pairs_reads_clone_and_sha_off_any_line():
    text = ledger(("A", "/work/scratch/A", SHA_A),
                  ("B", "/work/scratch/B", SHA_B),
                  # a second file in B's one commit: the same pair
                  ("B", "/work/scratch/B", SHA_B)) + "\n".join([
        "| D | Jobs/D | `/work/scratch/D` | `main` | `Jenkinsfile` | — |",
        "Prose naming /work/scratch/E and no commit at all.",
        "A commit alone: 1234abc, with no clone.",
        "- /work/scratch/F (deadbeef, then f00d123),",
        "|`/work/scratch/G`|`main`|`abc1234`|",
    ])
    assert run_loop.review_set_pairs(text) == [
        ("/work/scratch/A", SHA_A), ("/work/scratch/B", SHA_B),
        # the last sha on the line; a hex word with no digit is no sha
        ("/work/scratch/F", "f00d123"),
        # a table written without spaces
        ("/work/scratch/G", "abc1234")]
    assert run_loop.review_set_pairs("") == []


def bump_row(clone, sha, parent):
    """A ledger row in slice 055's shape: the bump's sha, then its parent."""
    return (f"| B | Jobs/B | `{clone}` | `main` | `Jenkinsfile` | `{sha}` "
            f"| `{parent}` |\n")


def test_a_line_naming_two_commits_is_no_pair():
    """Slice 055's rows named each bump and then its parent, and the last
    sha handed the reviewer the parent (AIWF-62). A short and a full form
    of one commit are one commit."""
    text = (ledger(("A", "/work/scratch/A", SHA_A))
            + bump_row("/work/scratch/B", SHA_B, SHA_B2)
            + f"- /work/scratch/C: {SHA_C[:7]} ({SHA_C})\n"
            + f"- /work/scratch/D: {SHA_A}, then {SHA_A[:9]}\n")
    assert run_loop.review_set_pairs(text) == [
        ("/work/scratch/A", SHA_A), ("/work/scratch/C", SHA_C),
        ("/work/scratch/D", SHA_A)]


def test_review_set_ambiguous_reads_the_lines_naming_two_commits():
    text = (ledger(("A", "/work/scratch/A", SHA_A))
            + bump_row("/work/scratch/B", SHA_B, SHA_B2)
            # the same row again: one line
            + bump_row("/work/scratch/B", SHA_B, SHA_B2)
            + f"- /work/scratch/C: {SHA_C[:7]} ({SHA_C})\n"
            # a short form, a second commit, the full form: two commits,
            # each where it first appears, the longer form kept
            + f"- /work/scratch/E: {SHA_C[:8]}, 1234abc, {SHA_C}\n")
    assert run_loop.review_set_ambiguous(text) == [
        ("/work/scratch/B", (SHA_B, SHA_B2)),
        ("/work/scratch/E", (SHA_C, "1234abc"))]
    assert run_loop.review_set_ambiguous("") == []


def test_the_review_line_is_parsed_plain_or_bold():
    phases, errors = parse_plan(
        "### P1 — Plain\n\nTarget: app\n\nReview: migration-ledger.md\n"
        "Review: second.md\n\n"
        "### P2 — Bold\n\n**Target:** `root`\n**Review:** "
        "`notes/ledger.md`\n\n"
        "### P3 — None\n\nTarget: app\n\nReviewers read the ledger.\n")
    assert not errors
    assert [p.review for p in phases] == [
        "migration-ledger.md", "notes/ledger.md", None]
    assert phases[1].target == "root"


def review_set_slice(tmp, review="Review: ledger.md\n"):
    return make_slice(tmp, phases=[("1", "Migrate", PROJECT, False, review)])


def writes(path, text):
    """A script step's effect: the session wrote `text` to `path`."""
    def effect(loop):
        Path(path).write_text(text)
    return effect


def reviews_of(r):
    return [p for role, p in r.prompts if role == "code-reviewer"]


def test_the_reviewer_is_pointed_at_the_pairs_the_phase_added_or_changed():
    """A pair already in the file when the phase began is not this phase's;
    one whose sha changed is, and so is a new one — in a delta round too."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = review_set_slice(tmp)
        path = slice_dir / "ledger.md"
        path.write_text(ledger(("A", "/work/scratch/A", SHA_A),
                               ("B", "/work/scratch/B", SHA_B)))
        mine = ledger(("A", "/work/scratch/A", SHA_A),
                      ("B", "/work/scratch/B", SHA_B2),
                      ("C", "/work/scratch/C", SHA_C))

        def fixes(loop):
            path.write_text(mine.replace(SHA_C, "c0ffee1"))
            loop.fake_git.head = "fixhead"

        r = ScriptedLoop(slice_dir, [
            (*V["exec_done"], writes(path, mine)), V["review_issues"],
            (*V["exec_done"], fixes), V["review_signoff"], *TAIL],
            repo_root=repo)
        assert run_to_exit(r) == 0 and not r.script
        assert load_state(slice_dir)["phases"]["1"]["review_set_start"] == [
            ["/work/scratch/A", SHA_A], ["/work/scratch/B", SHA_B]]
        first, delta = reviews_of(r)
        assert (f"plan.md's `Review:` line for this phase names `{path}`"
                in first.replace("\n", " "))
        assert ("\n\n- `git -C /work/scratch/B show " + SHA_B2 + "`\n"
                "- `git -C /work/scratch/C show " + SHA_C + "`\n\n") in first
        assert SHA_A not in first and SHA_B not in first
        assert "is empty" not in first
        assert ("the review set's repos (/work/scratch/B, /work/scratch/C)"
                in first.replace("\n", " "))
        assert "ran GREEN on this exact commit" in first
        assert "\n\n\n" not in first
        assert "Re-review phase P1" in delta
        assert "`git -C /work/scratch/C show c0ffee1`" in delta
        assert SHA_C not in delta
        log = (slice_dir / "log.txt").read_text()
        assert "[P1] reviewer told: review set of 2 pair(s) from ledger.md" \
            in log


def test_a_review_set_over_an_empty_target_range_is_the_phases_work():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = review_set_slice(tmp)
        path = slice_dir / "ledger.md"
        r = ScriptedLoop(slice_dir, [
            (*V["exec_done"], writes(path, ledger(
                ("A", "/work/scratch/A", SHA_A)))),
            V["review_signoff"], *TAIL], repo_root=repo)
        r.fake_git.trees = {"base123": "tree0", "HEAD": "tree0"}
        assert run_to_exit(r) == 0
        assert load_state(slice_dir)["phases"]["1"]["review_set_start"] == []
        prompt = reviews_of(r)[0]
        assert f"- `git -C /work/scratch/A show {SHA_A}`" in prompt
        assert (f"The Target's own range, `git diff base123..HEAD` in {repo}, "
                "is empty: these pairs are the phase's work.") \
            in prompt.replace("\n", " ")
        assert "\n\n\n" not in prompt
        assert ("[P1] reviewer told: review set of 1 pair(s) from ledger.md, "
                "Target range empty") in (slice_dir / "log.txt").read_text()


def test_a_declared_review_set_with_nothing_new_is_flagged():
    # the file never written: it does not exist; the Target has work
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = review_set_slice(tmp, "**Review:** `ledger.md`\n")
        r = ScriptedLoop(slice_dir, [V["exec_done"], V["review_signoff"],
                                     *TAIL], repo_root=repo)
        assert run_to_exit(r) == 0
        prompt = reviews_of(r)[0].replace("\n", " ")
        assert (f"declares a review set outside its Target, "
                f"`{slice_dir / 'ledger.md'}`, and that file does not exist; "
                f"the Target's own range, `git diff base123..HEAD` in {repo}, "
                "is not empty. Report it in your review") in prompt
        assert "find it and name where" in prompt
        assert "git -C" not in prompt and "suite alone" not in prompt
        assert "[P1] reviewer told: review set ledger.md does not exist" \
            in (slice_dir / "log.txt").read_text()
    # the file holds only what it held before the phase; the range is empty
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = review_set_slice(tmp)
        (slice_dir / "ledger.md").write_text(
            ledger(("A", "/work/scratch/A", SHA_A)))
        r = ScriptedLoop(slice_dir, [V["exec_done"], V["review_signoff"],
                                     *TAIL], repo_root=repo)
        r.fake_git.trees = {"base123": "tree0", "HEAD": "tree0"}
        assert run_to_exit(r) == 0
        prompt = reviews_of(r)[0]
        assert ("it holds no clone and commit pair this phase added or "
                "changed; the Target's own range, `git diff base123..HEAD` "
                f"in {repo}, is empty too.") in prompt.replace("\n", " ")
        assert SHA_A not in prompt
        assert "\n\n\n" not in prompt
        assert ("[P1] reviewer told: review set ledger.md has no new pair, "
                "Target range empty") in (slice_dir / "log.txt").read_text()


def test_an_empty_target_range_with_no_review_set_is_flagged():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r = ScriptedLoop(slice_dir, [V["exec_done"], V["review_signoff"],
                                     *TAIL], repo_root=repo)
        r.fake_git.trees = {"base123": "tree0", "HEAD": "tree0"}
        assert run_to_exit(r) == 0
        assert load_state(slice_dir)["phases"]["1"]["review_set_start"] \
            is None
        prompt = reviews_of(r)[0]
        assert (f"`git diff base123..HEAD` in {repo} is empty — the phase "
                "committed nothing to its Target, and plan.md declares no "
                "review set outside it") in prompt.replace("\n", " ")
        assert "\n\n\n" not in prompt
        assert "[P1] reviewer told: Target range empty, no review set " \
            "declared" in (slice_dir / "log.txt").read_text()


def test_target_work_and_no_review_set_leave_the_dispatch_as_it_was():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r = ScriptedLoop(slice_dir, [V["exec_done"], V["review_signoff"],
                                     *TAIL], repo_root=repo)
        assert run_to_exit(r) == 0
        prompt = reviews_of(r)[0]
        assert "review set" not in prompt and "is empty" not in prompt
        assert "not a finding.\n\nThe deterministic test gate ran GREEN" \
            in prompt
        assert "reviewer told" not in (slice_dir / "log.txt").read_text()


def test_a_snapshot_less_phase_state_counts_every_pair():
    """A phase begun on a plugin that took no snapshot reads as an empty
    baseline; an off-shape entry is skipped, never a crash."""
    read = RunLoop._review_set_start
    assert read({}) == set() and read({"review_set_start": None}) == set()
    assert read({"review_set_start": [["/c", "abc1234"], ["/x"], "junk",
                                      [1, 2]]}) == {("/c", "abc1234")}


def test_a_line_naming_two_commits_is_flagged_and_handed_on_as_no_pair():
    """Slice 055's shape (AIWF-62): a good row and a bump row naming its
    parent after it. The good row is a pair; the bump row is shown to the
    reviewer to find the phase's commit, and neither of its shas is."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = review_set_slice(tmp)
        path = slice_dir / "ledger.md"
        mine = (ledger(("A", "/work/scratch/A", SHA_A))
                + bump_row("/work/scratch/B", SHA_B, SHA_B2))
        r = ScriptedLoop(slice_dir, [
            (*V["exec_done"], writes(path, mine)), V["review_signoff"],
            *TAIL], repo_root=repo)
        assert run_to_exit(r) == 0
        assert load_state(slice_dir)["phases"]["1"][
            "review_set_ambiguous_start"] == []
        prompt = reviews_of(r)[0]
        assert (f"- `git -C /work/scratch/A show {SHA_A}`\n\n"
                f"plan.md's `Review:` line for this phase names `{path}`, "
                "and these lines") in prompt
        assert "git -C /work/scratch/B show" not in prompt
        assert ("each name more than one commit for one clone"
                in prompt.replace("\n", " "))
        assert f"\n\n- `/work/scratch/B`: `{SHA_B}`, `{SHA_B2}`\n\n" in prompt
        assert ("say in your review which commit you took\nfor each line.\n\n"
                "The deterministic test gate ran GREEN") in prompt
        assert "is empty" not in prompt
        assert ("the review set's repos (/work/scratch/A, /work/scratch/B)"
                in prompt.replace("\n", " "))
        assert "\n\n\n" not in prompt
        log = (slice_dir / "log.txt").read_text()
        assert "[P1] reviewer told: review set of 1 pair(s) from ledger.md\n" \
            in log
        assert ("[P1] reviewer told: ledger.md has 1 line(s) naming more than "
                f"one commit: /work/scratch/B ({SHA_B}, {SHA_B2})\n") in log


def test_only_lines_naming_two_commits_over_an_empty_range_are_flagged():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = review_set_slice(tmp)
        path = slice_dir / "ledger.md"
        r = ScriptedLoop(slice_dir, [
            (*V["exec_done"], writes(path, ledger() + bump_row(
                "/work/scratch/B", SHA_B, SHA_B2))),
            V["review_signoff"], *TAIL], repo_root=repo)
        r.fake_git.trees = {"base123": "tree0", "HEAD": "tree0"}
        assert run_to_exit(r) == 0
        prompt = reviews_of(r)[0]
        flat = prompt.replace("\n", " ")
        assert "each name more than one commit for one clone" in flat
        assert f"- `/work/scratch/B`: `{SHA_B}`, `{SHA_B2}`" in prompt
        assert ("for each line.\n\n"
                + run_loop.REVIEW_SET_AMBIGUOUS_EMPTY_RANGE.format(
                    merge_base="base123", root=repo)
                + "\n\nThe deterministic test gate") in prompt
        assert (f"The Target's own range, `git diff base123..HEAD` in {repo}, "
                "is empty: the phase's work is what the lines above name."
                ) in flat
        assert "holds no clone and commit pair" not in flat
        assert "these pairs are the phase's work" not in flat
        assert "git -C /work/scratch/B show" not in prompt
        assert "the review set's repos (/work/scratch/B)" in flat
        assert "\n\n\n" not in prompt
        log = (slice_dir / "log.txt").read_text()
        assert ("[P1] reviewer told: ledger.md has 1 line(s) naming more than "
                f"one commit: /work/scratch/B ({SHA_B}, {SHA_B2}), Target "
                "range empty\n") in log
        assert "has no new pair" not in log and "review set of" not in log


def test_a_line_naming_two_commits_before_the_phase_is_not_flagged():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = review_set_slice(tmp)
        (slice_dir / "ledger.md").write_text(
            ledger(("A", "/work/scratch/A", SHA_A))
            + bump_row("/work/scratch/B", SHA_B, SHA_B2))
        r = ScriptedLoop(slice_dir, [V["exec_done"], V["review_signoff"],
                                     *TAIL], repo_root=repo)
        assert run_to_exit(r) == 0
        ps = load_state(slice_dir)["phases"]["1"]
        assert ps["review_set_start"] == [["/work/scratch/A", SHA_A]]
        assert ps["review_set_ambiguous_start"] == [
            ["/work/scratch/B", [SHA_B, SHA_B2]]]
        prompt = reviews_of(r)[0]
        assert ("it holds no clone and commit pair this phase added or "
                "changed") in prompt.replace("\n", " ")
        assert "more than one commit" not in prompt.replace("\n", " ")
        assert SHA_B not in prompt and SHA_B2 not in prompt
        log = (slice_dir / "log.txt").read_text()
        assert "[P1] reviewer told: review set ledger.md has no new pair" \
            in log
        assert "naming more than one commit" not in log


def test_a_snapshot_less_phase_state_flags_every_line_naming_two_commits():
    read = RunLoop._review_set_ambiguous_start
    assert read({}) == set()
    assert read({"review_set_ambiguous_start": None}) == set()
    assert read({"review_set_ambiguous_start": [
        ["/c", ["abc1234", "def5678"]], ["/x"], "junk", [1, ["abc1234"]],
        ["/y", "abc1234"], ["/z", ["abc1234", 5]]]}) == {
        ("/c", ("abc1234", "def5678"))}


# -- Secret data in the diffs agents read (AIWF-51) ---------------------------
#
# Slice 050 removed five Secrets, and the doc-writer's diff file and the
# reviewer's own `git diff` carried every CA key and password into their
# transcripts. The fakes' diffs are shaped as git writes them, and the blobs
# the redactor reads at both ends of a range come from `FakeGit.blobs`.

SECRET_PATH = "secrets/ca.yaml"
SECRET_TEXT = ("apiVersion: v1\nkind: Secret\nmetadata:\n  name: ca-key\n"
               "type: Opaque\ndata:\n  ca.key: S3CRETKEYVALUE\n"
               "  password: aHVudGVyMg==\n")
SECRET_VALUES = ("S3CRETKEYVALUE", "aHVudGVyMg", "M1DKEYVALUE", "N3WKEYVALUE")


def secret_removal(text=SECRET_TEXT, path=SECRET_PATH):
    """git's diff of `path` deleted, `text` its blob before."""
    lines = text.splitlines()
    return (f"diff --git a/{path} b/{path}\ndeleted file mode 100644\n"
            f"index 1234567..0000000\n--- a/{path}\n+++ /dev/null\n"
            f"@@ -1,{len(lines)} +0,0 @@\n"
            + "".join(f"-{line}\n" for line in lines))


def secret_change(old_value, new_value, path=SECRET_PATH):
    """git's diff of the Secret's `ca.key` changed, and the blobs at either
    end — the hunk's context, as git's would, reaches neither the kind line
    nor the name."""
    old = SECRET_TEXT.replace("S3CRETKEYVALUE", old_value)
    new = SECRET_TEXT.replace("S3CRETKEYVALUE", new_value)
    diff = (f"diff --git a/{path} b/{path}\nindex 1111111..2222222 100644\n"
            f"--- a/{path}\n+++ b/{path}\n@@ -4,5 +4,5 @@ kind: Secret\n"
            "   name: ca-key\n type: Opaque\n data:\n"
            f"-  ca.key: {old_value}\n+  ca.key: {new_value}\n"
            "   password: aHVudGVyMg==\n")
    return diff, old, new


def assert_no_secret_on_disk(slice_dir):
    """No file the run wrote — state, log, bail, report, diffs — holds a
    value."""
    for path in slice_dir.rglob("*"):
        if path.is_file():
            text = path.read_text(errors="replace")
            assert not any(v in text for v in SECRET_VALUES), path


def test_the_doc_phase_diff_stubs_secret_data_and_ignores_itself():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r = ScriptedLoop(slice_dir, [V["exec_done"], V["review_signoff"],
                                     *TAIL], repo_root=repo)
        r.fake_git.stat = (f" {SECRET_PATH} | 8 --------\n"
                           " 1 file changed, 8 deletions(-)")
        r.fake_git.diff = secret_removal()
        r.fake_git.blobs = {("base123", SECRET_PATH): SECRET_TEXT}
        assert run_to_exit(r) == 0
        out_dir = slice_dir / "doc_phase"
        assert (out_dir / ".gitignore").read_text() == "*\n"
        text = (out_dir / "repo.diff").read_text()
        assert text.startswith(f"{repo} — P1: git diff base123..abc123\n\n"
                               f" {SECRET_PATH} | 8 --------\n")
        lines = text.splitlines()
        assert "-[Secret ca-key: 2 data lines]" in lines
        assert "-kind: Secret" in lines and "-data:" in lines
        assert text.endswith("-data:\n-[Secret ca-key: 2 data lines]\n")
        assert ("show", f"base123:{SECRET_PATH}") in [
            c for _, c in r.fake_git.calls]
        assert_no_secret_on_disk(slice_dir)
        prompt = next(p for role, p in r.prompts if role == "doc-writer")
        assert ("and this file already is that. Every line inside a `kind: "
                "Secret`'s `data:` or `stringData:` is a `[Secret <name>: N "
                "data lines]` stub there: a doc needs no more of it, so never "
                "read it back from git or the files themselves.") \
            in " ".join(prompt.split())
        assert (f"doc phase: 2 Secret data line(s) stubbed in "
                f"{out_dir / 'repo.diff'}") in (slice_dir / "log.txt").read_text()


def test_a_doc_phase_diff_it_cannot_redact_bails_and_writes_none_of_it():
    flow = ("apiVersion: v1\nkind: Secret\nmetadata:\n  name: ca-key\n"
            "data: {password: aHVudGVyMg==}\n")
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r = ScriptedLoop(slice_dir, [V["exec_done"], V["review_signoff"],
                                     V["consult_complete"], V["test_clean"]],
                         repo_root=repo)
        r.fake_git.stat = (f" {SECRET_PATH} | 5 -----\n"
                           " 1 file changed, 5 deletions(-)")
        r.fake_git.diff = secret_removal(flow)
        r.fake_git.blobs = {("base123", SECRET_PATH): flow}
        assert run_to_exit(r) == 3
        bail = json.loads((slice_dir / "bailout.json").read_text())
        assert bail["reason"] == "redaction"
        assert bail["question"] is False and bail["phase"] is None
        assert f"{SECRET_PATH} (old side), line 5" in bail["details"]
        assert (f"in base123..abc123 of {repo}; the driver hands no agent a "
                "diff it could not redact") in bail["details"]
        assert "doc-writer" not in [s[0] for s in r.spawned]
        assert not list((slice_dir / "doc_phase").glob("*.diff"))
        assert_no_secret_on_disk(slice_dir)


def test_a_review_range_with_secret_data_is_handed_over_redacted():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r = ScriptedLoop(slice_dir, [V["exec_done"], V["review_signoff"],
                                     *TAIL], repo_root=repo)
        diff, old, new = secret_change("S3CRETKEYVALUE", "N3WKEYVALUE00")
        r.fake_git.diff_files = f"app/main.py\n{SECRET_PATH}"
        r.fake_git.stat = (f" {SECRET_PATH} | 2 +-\n"
                           " 1 file changed, 1 insertion(+), 1 deletion(-)")
        r.fake_git.diff = diff
        r.fake_git.blobs = {("base123", SECRET_PATH): old,
                            ("abc123", SECRET_PATH): new}
        assert run_to_exit(r) == 0
        path = slice_dir / "phases" / "P1" / "review_r1.diff"
        text = path.read_text()
        assert text.startswith(f"{repo} — git diff base123..abc123\n\n"
                               f" {SECRET_PATH} | 2 +-\n")
        # the section heading git took from the file is dropped
        assert text.splitlines()[-7:] == [
            "@@ -4,5 +4,5 @@", "   name: ca-key", " type: Opaque", " data:",
            "-[Secret ca-key: 1 data line]", "+[Secret ca-key: 1 data line]",
            " [Secret ca-key: 1 data line]"]
        assert_no_secret_on_disk(slice_dir)
        prompt = reviews_of(r)[0]
        note = run_loop.REVIEW_SECRETS_NOTE.format(
            path=path, ranges="`base123..abc123`", held_out="", root=repo,
            tool=run_loop.TOOLS_DIR / "redact_secrets.py")
        assert "not a finding.\n\n" + note + "The deterministic test gate" \
            in prompt
        assert "never to print" not in prompt
        assert (f"[P1] reviewer handed {path}: 3 Secret data line(s) stubbed"
                in (slice_dir / "log.txt").read_text())


def test_a_review_range_of_code_alone_costs_one_name_only_and_nothing_more():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r = ScriptedLoop(slice_dir, [V["exec_done"], V["review_signoff"],
                                     *TAIL], repo_root=repo)
        # prose about Secrets is no manifest
        r.fake_git.diff_files = "app/main.py\ndocs/secrets.md"
        assert run_to_exit(r) == 0
        assert not (slice_dir / "phases" / "P1" / "review_r1.diff").exists()
        prompt = reviews_of(r)[0]
        assert "Secret" not in prompt and "never to print" not in prompt
        assert "not a finding.\n\nThe deterministic test gate ran GREEN" \
            in prompt
        calls = [c for _, c in r.fake_git.calls]
        assert [c for c in calls if c[:2] == ("diff", "--name-only")
                and "--no-renames" in c] == [
            ("diff", "--name-only", "--no-renames", "base123..abc123")]
        assert not [c for c in calls if c[0] == "diff"
                    and "--name-only" not in c
                    and not any(a.startswith("--stat") for a in c)]
        assert not [c for c in calls if c[0] == "show"]


def test_never_print_paths_are_parsed_held_out_and_given_the_safe_shape():
    phases, errors = parse_plan(
        "### P1 — Keys\n\n**Target:** app\n"
        "**Never print:** `secrets/ca.yaml`, keys/x.pem\n"
        "Never print: later.yaml\n\n"
        "### P2 — None\n\nTarget: app\n")
    assert not errors
    assert [p.never_print for p in phases] == [
        ["secrets/ca.yaml", "keys/x.pem"], None]
    tool = run_loop.TOOLS_DIR / "redact_secrets.py"
    spec = ("--", ".", ":(exclude)secrets/ca.yaml", ":(exclude)keys/x.pem")
    for touched in ("app/main.py", "deploy/app.yaml"):
        with tempfile.TemporaryDirectory() as tmp:
            slice_dir, repo = make_slice(tmp, phases=[(
                "1", "Keys", PROJECT, False,
                "Never print: secrets/ca.yaml, `keys/x.pem`\n")])
            r = ScriptedLoop(slice_dir, [V["exec_done"], V["review_signoff"],
                                         *TAIL], repo_root=repo)
            diff, old, new = secret_change("S3CRETKEYVALUE", "N3WKEYVALUE00",
                                           path="deploy/app.yaml")
            r.fake_git.diff_files = touched
            r.fake_git.diffs = [diff]
            r.fake_git.blobs = {("base123", "deploy/app.yaml"): old,
                                ("abc123", "deploy/app.yaml"): new}
            assert run_to_exit(r) == 0
            prompt = reviews_of(r)[0]
            flat = " ".join(prompt.split())
            assert ("plan.md marks `secrets/ca.yaml`, `keys/x.pem` never to "
                    "print for this phase.") in flat
            assert (f"`git -C {repo} diff <range> -- . "
                    "':(exclude)secrets/ca.yaml' ':(exclude)keys/x.pem' | "
                    f"python3 {tool} --root {repo} <range>`, where `<range>` "
                    "is `base123..abc123`.") in flat
            assert f"Run `git -C {repo} diff --stat <range>` first" in flat
            calls = [c for _, c in r.fake_git.calls]
            assert ("diff", "--name-only", "--no-renames", "base123..abc123",
                    *spec) in calls
            if touched == "app/main.py":
                assert "kind: Secret" not in prompt
                assert "not a finding.\n\nplan.md marks" in prompt
                assert ("diff", "base123..abc123", *spec) not in calls
                continue
            # the Secret note first, saying the paths are held out of its file
            assert prompt.index("This range changes `kind: Secret`") \
                < prompt.index("plan.md marks")
            assert ("stub, the never-print paths below held out. Read the "
                    "diff") in flat
            assert ("diff", "base123..abc123", *spec) in calls
            assert ("diff", "--stat=100", "base123..abc123") in calls
            assert_no_secret_on_disk(slice_dir)


def test_a_delta_round_hands_over_the_fix_range_then_the_branch():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)

        def move_head(loop):
            loop.fake_git.head = "head2"

        r = ScriptedLoop(slice_dir, [
            V["exec_done"], V["review_issues"],
            ("code-writer", {"outcome": "done", "summary": "fixed"},
             move_head),
            V["review_signoff"], *TAIL], repo_root=repo)
        first, base_text, mid = secret_change("S3CRETKEYVALUE",
                                              "M1DKEYVALUE00")
        fix, _, new = secret_change("M1DKEYVALUE00", "N3WKEYVALUE00")
        branch, _, _ = secret_change("S3CRETKEYVALUE", "N3WKEYVALUE00")
        r.fake_git.diff_files = SECRET_PATH
        r.fake_git.diffs = [first, fix, branch]
        r.fake_git.blobs = {("base123", SECRET_PATH): base_text,
                            ("abc123", SECRET_PATH): mid,
                            ("head2", SECRET_PATH): new}
        assert run_to_exit(r) == 0 and not r.fake_git.diffs
        outputs = slice_dir / "phases" / "P1"
        assert (outputs / "review_r1.diff").exists()
        text = (outputs / "review_r2.diff").read_text()
        assert text.startswith(f"{repo} — git diff abc123..head2\n")
        assert f"\n{repo} — git diff base123..head2\n" in text
        assert text.count("-[Secret ca-key: 1 data line]") == 2
        assert_no_secret_on_disk(slice_dir)
        delta = reviews_of(r)[1]
        assert "Re-review phase P1" in delta
        flat = " ".join(delta.split())
        assert (f"{outputs / 'review_r2.diff'} holds `git diff --stat` and "
                "then the diff for the fix range `abc123..head2` and then "
                "the whole branch `base123..head2`, every line") in flat
        calls = [c for _, c in r.fake_git.calls if c[:2] == ("diff", "--name-only")
                 and "--no-renames" in c]
        assert [c[3] for c in calls] == ["base123..abc123", "abc123..head2",
                                         "base123..head2"]


def test_a_review_range_it_cannot_redact_bails_before_the_reviewer():
    flow = ("apiVersion: v1\nkind: Secret\nmetadata:\n  name: ca-key\n"
            "data: {password: aHVudGVyMg==}\n")
    for blobs, why in (({("base123", SECRET_PATH): flow},
                        f"{SECRET_PATH} (old side), line 5"),
                       ({}, f"{SECRET_PATH} (old side): the blob at base123 "
                            "could not be read")):
        with tempfile.TemporaryDirectory() as tmp:
            slice_dir, repo = make_slice(tmp)
            r = ScriptedLoop(slice_dir, [V["exec_done"], V["review_signoff"],
                                         *TAIL], repo_root=repo)
            r.fake_git.diff_files = SECRET_PATH
            r.fake_git.diff = secret_removal(flow)
            r.fake_git.blobs = blobs
            assert run_to_exit(r) == 3
            bail = json.loads((slice_dir / "bailout.json").read_text())
            assert bail["reason"] == "redaction" and bail["phase"] == "1"
            assert bail["question"] is False
            assert why in bail["details"]
            assert (f"in base123..abc123 of {repo}; the driver hands no agent "
                    "a diff it could not redact") in bail["details"]
            assert [s[0] for s in r.spawned] == ["code-writer"]
            assert not (slice_dir / "phases" / "P1" / "review_r1.diff").exists()
            assert_no_secret_on_disk(slice_dir)


# -- kc's "nothing ran" exit code (KC-81) --------------------------------------
#
# `kc project test|build|lint` exits 3 when its selection holds no statement
# for the verb. Read as red, a target with no tests spawned fix rounds that
# could fix nothing and bailed `gate_red`; read as green, the sweep claimed a
# lint no component defines.

class KcExitLoop(ScriptedLoop):
    """ScriptedLoop running the driver's OWN phase gate and sweep command —
    only the kc process behind them is scripted, by exit code: `gate_rcs` in
    order for the phase gate's every other command (0 once spent),
    `lint_rcs` in order for its `kc project lint` commands (3 once spent: a
    project with no lint to run, so a test that scripts none sees the gate
    it always did), `sweep_rcs` by (component, verb) for the loop-tail
    sweep (0 when absent)."""

    _run_gate = RunLoop._run_gate
    _run_sweep_cmd = RunLoop._run_sweep_cmd

    def __init__(self, slice_dir, script, gate_rcs=(), sweep_rcs=None,
                 lint_rcs=(), **kw):
        super().__init__(slice_dir, script, **kw)
        self.gate_rcs = list(gate_rcs)
        self.lint_rcs = list(lint_rcs)
        self.sweep_rcs = dict(sweep_rcs or {})
        self.kc_runs = []    # (argv, cwd, rc)
        # kc_runs' phase-gate rows, sweep apart: its lint commands apart from
        # the rest, and every one of them in the order run
        self.phase_gate_runs = []
        self.phase_lint_runs = []
        self.phase_gate_order = []
        self._sweeping = False

    def _run_gate_sweep(self, targets, heads):
        self._sweeping = True
        try:
            return super()._run_gate_sweep(targets, heads)
        finally:
            self._sweeping = False

    def _gate_exec(self, argv, cwd, log_file):
        lint = argv[:3] == ["kc", "project", "lint"]
        if self._sweeping:
            rc_ = self.sweep_rcs.get((argv[4], argv[2]), 0)
        elif lint:
            rc_ = self.lint_rcs.pop(0) if self.lint_rcs else 3
        else:
            rc_ = self.gate_rcs.pop(0) if self.gate_rcs else 0
        self.kc_runs.append((list(argv), Path(cwd), rc_))
        if not self._sweeping:
            (self.phase_lint_runs if lint
             else self.phase_gate_runs).append(self.kc_runs[-1])
            self.phase_gate_order.append(self.kc_runs[-1])
        log_file.write(f"{' '.join(argv)}: exit {rc_}\n")
        return rc_


def test_the_drivers_gate_reads_kcs_exit_codes():
    """0 green (recorded), 1 red (a fix round), 2 a usage error (a driver
    bug, never a red suite)."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r = KcExitLoop(slice_dir, [V["exec_done"], V["exec_done"],
                                   V["review_signoff"], *TAIL],
                       repo_root=repo, gate_rcs=[1, 0])
        assert run_to_exit(r) == 0
        assert not r.script
        ps = load_state(slice_dir)["phases"]["1"]
        assert ps["gate_fix_rounds"] == 1
        assert ps["gate_green_commit"] == r.fake_git.head
        assert r.kc_runs[0][:2] == (["kc", "project", "test", "--project",
                                     PROJECT], repo)
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r = KcExitLoop(slice_dir, [V["exec_done"]], repo_root=repo,
                       gate_rcs=[2])
        assert run_to_exit(r) == 3
        bail = json.loads((slice_dir / "bailout.json").read_text())
        assert bail["reason"] == "protocol_failure"


def test_a_gate_that_ran_nothing_proceeds_unverified_without_a_fix_round():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r = KcExitLoop(slice_dir, [V["exec_done"], V["review_signoff"],
                                   *TAIL],
                       repo_root=repo, gate_rcs=[3, 3])
        assert run_to_exit(r) == 0
        assert not r.script, "no fix round was spawned"
        state = load_state(slice_dir)
        ps = state["phases"]["1"]
        assert ps["status"] == "merged" and ps["gate_fix_rounds"] == 0
        assert ps["gate_green_commit"] is None
        assert ps["gate_nothing_ran_commit"] == r.fake_git.head
        # the gate stage's run and the merge stage's re-gate (no green on
        # record at the head) both ran nothing, and neither bailed
        assert [h["outcome"] for h in state["history"]
                if h["role"] == "gate"] == ["nothing_ran", "nothing_ran"]
        prompt = next(p for role, p in r.prompts
                      if role == "code-reviewer").replace("\n", " ")
        assert (f"`kc project test --project {PROJECT}` in {repo} ran nothing "
                f"on this exact commit ({r.fake_git.head[:12]})") in prompt
        assert "the target defines no tests" in prompt
        assert "GREEN" not in prompt
        assert f"{PROJECT} defines no tests — proceeding" \
            in (slice_dir / "log.txt").read_text()


def test_the_nothing_ran_line_is_stated_only_about_the_commit_it_ran_on():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r = ScriptedLoop(slice_dir, [], repo_root=repo)
        target = run_loop.ResolvedTarget(
            PROJECT, "project", Path(repo),
            ["kc", "project", "test", "--project", PROJECT], Path(repo))
        ps = {"gate_nothing_ran_commit": "deadbeefcafe0"}
        assert "defines no tests" in r._gate_line(ps, "deadbeefcafe0",
                                                    target)
        # a later commit, or a target with no gate at all: plainly unverified
        assert r._gate_line(ps, "0ther000head0", target) \
            == run_loop.GATE_UNVERIFIED_LINE
        no_gate = run_loop.ResolvedTarget("../Sib", "sibling", Path(repo),
                                          None, Path(repo))
        assert r._gate_line(ps, "deadbeefcafe0", no_gate) \
            == run_loop.GATE_UNVERIFIED_LINE


# -- `Target: root`: root's own tests, else the whole repo (AIWF-26) ----------
#
# FieldnotesApp's root declares no `test:` on purpose, so `--project root`
# exited 3 and every root phase passed unverified; KubeCoder's root owns the
# whole Python gate, where bare `kc project test` would run every component's
# suite as well. The gate runs root's own first and bare only when it ran
# nothing.

def root_components(cwd):
    return {PROJECT: Path(cwd), "root": Path(cwd)}


def root_gate_run(tmp, script, gate_rcs, lint_rcs=()):
    slice_dir, repo = make_slice(tmp, phases=[("1", "First phase", "root")])
    r = KcExitLoop(slice_dir, script, repo_root=repo, gate_rcs=gate_rcs,
                   lint_rcs=lint_rcs)
    with patched(run_loop, load_project_dirs=root_components):
        code = run_to_exit(r)
    return slice_dir, repo, r, code


ROOT_ARGV = ["kc", "project", "test", "--project", "root"]
BARE_ARGV = ["kc", "project", "test"]
ROOT_LINT_ARGV = ["kc", "project", "lint", "--project", "root"]
BARE_LINT_ARGV = ["kc", "project", "lint"]


def test_a_root_gate_that_ran_nothing_falls_back_to_the_whole_repo():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo, r, code = root_gate_run(
            tmp, [V["exec_done"], V["review_signoff"], *TAIL], [3, 0])
        assert code == 0 and not r.script
        assert [(argv, cwd) for argv, cwd, _ in r.phase_gate_runs] == [
            (ROOT_ARGV, repo), (BARE_ARGV, repo)]
        state = load_state(slice_dir)
        ps = state["phases"]["1"]
        assert ps["gate_green_commit"] == r.fake_git.head
        assert ps["gate_cmd"] == "kc project test"
        # one gate run, one history row, one log holding both commands
        assert [h["outcome"] for h in state["history"]
                if h["role"] == "gate"] == ["green"]
        log = Path(ps["gate_green_log"]).read_text()
        assert log.index("--project root: exit 3") \
            < log.index("kc project test: exit 0")
        prompt = next(p for role, p in r.prompts
                      if role == "code-reviewer").replace("\n", " ")
        assert f"`kc project test` in {repo} — with full output in" in prompt
        assert "--project root` in" not in prompt
        narration = (slice_dir / "log.txt").read_text()
        assert ("`kc project test --project root` ran nothing — root "
                "declares no tests, so the gate is the whole repo") \
            in narration


def test_a_red_whole_repo_gate_after_an_empty_root_is_a_red_gate():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo, r, code = root_gate_run(
            tmp, [V["exec_done"], V["exec_done"], V["review_signoff"], *TAIL],
            [3, 1, 3, 0])
        assert code == 0 and not r.script
        state = load_state(slice_dir)
        assert state["phases"]["1"]["gate_fix_rounds"] == 1
        assert [h["outcome"] for h in state["history"]
                if h["role"] == "gate"] == ["red", "green"]
        writers = [p for role, p in r.prompts if role == "code-writer"]
        assert "The gate went red on `kc project test`;" in writers[1]
        # the one review came after the fix round's green, never the red
        reviews = [p for role, p in r.prompts if role == "code-reviewer"]
        assert len(reviews) == 1
        assert [argv for argv, _, _ in r.phase_gate_runs] == [
            ROOT_ARGV, BARE_ARGV, ROOT_ARGV, BARE_ARGV]
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo, r, code = root_gate_run(
            tmp, [V["exec_done"]] * (run_loop.GATE_FIX_CAP + 1),
            [3, 1] * (run_loop.GATE_FIX_CAP + 1))
        assert code == 3
        bail = json.loads((slice_dir / "bailout.json").read_text())
        assert bail["reason"] == "gate_red"
        assert not any(role == "code-reviewer" for role, _ in r.prompts)
        assert load_state(slice_dir)["phases"]["1"]["gate_green_commit"] \
            is None


def test_a_root_gate_with_tests_of_its_own_never_runs_the_whole_repo():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo, r, code = root_gate_run(
            tmp, [V["exec_done"], V["review_signoff"], *TAIL], [0])
        assert code == 0
        assert [argv for argv, _, _ in r.phase_gate_runs] == [ROOT_ARGV]
        prompt = next(p for role, p in r.prompts
                      if role == "code-reviewer").replace("\n", " ")
        assert f"`kc project test --project root` in {repo} — with full " \
            "output" in prompt


def test_a_component_gate_that_ran_nothing_never_falls_back():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r = KcExitLoop(slice_dir, [V["exec_done"], V["review_signoff"],
                                   *TAIL],
                       repo_root=repo, gate_rcs=[3, 3])
        assert run_to_exit(r) == 0
        assert [argv for argv, _, _ in r.phase_gate_runs] == [
            ["kc", "project", "test", "--project", PROJECT]] * 2
        prompt = next(p for role, p in r.prompts
                      if role == "code-reviewer").replace("\n", " ")
        assert (f"`kc project test --project {PROJECT}` in {repo} ran nothing "
                "on this exact commit") in prompt
        assert "whole repo" not in (slice_dir / "log.txt").read_text()


def wrapper_cmd(outputs):
    """The `gate` wrapper over a phase's spec, as a gate hint names it."""
    return f"`python3 {run_loop.SCRIPT} gate {Path(outputs) / 'gate_spec.json'}`"


def test_every_component_gate_hint_says_what_exit_3_means():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r = ScriptedLoop(slice_dir, [], repo_root=repo)
        r.project_dirs = root_components(repo)
        outputs = slice_dir / "phases" / "P1"
        component = r._gate_hint(r._resolve_target(PROJECT), outputs,
                                 "base123")
        root = r._gate_hint(r._resolve_target("root"), outputs, "base123")
        assert component == (
            f" — through {wrapper_cmd(outputs)}, which runs the driver's own "
            f"gate: `kc project test --project {PROJECT}` and `kc project lint "
            f"--project {PROJECT}`, and both for every other component the "
            "phase's diff touches. "
            f"{run_loop.GATE_REUSE_HINT}. {run_loop.NOTHING_RAN_HINT}")
        assert root == (
            f" — through {wrapper_cmd(outputs)}, which runs the driver's own "
            "gate: `kc project test --project root`, and bare `kc project "
            "test`, every component once, when that runs nothing (exit 3), "
            "and the same two steps for `kc project lint`. "
            f"{run_loop.GATE_REUSE_HINT}. {run_loop.NOTHING_RAN_HINT}")
        assert "Exit 3 is kc's \"nothing ran\"" in run_loop.NOTHING_RAN_HINT


# -- a component Target gates every component its diff touches (AIWF-91) -----
#
# PilotApp's `Target: frontend` phase committed backend code and tests too; the
# gate ran frontend's suite alone, and its reviewer was told GREEN about it.
# The gate now runs each component the phase's diff touches after the
# Target's own, and the reviewer is told which projects the green covers.

def split_components(cwd):
    """A manifest whose components sit in directories of their own — one
    nested in another's — beside root, in manifest order."""
    cwd = Path(cwd)
    return {"root": cwd, "frontend": cwd / "frontend",
            "backend": cwd / "backend", "worker": cwd / "backend" / "worker"}


def component_argv(name):
    return ["kc", "project", "test", "--project", name]


def lint_argv(name):
    return ["kc", "project", "lint", "--project", name]


def gate_entry(name, outcome, lint=None):
    """`name`'s `gate_projects` entry: its test's outcome, and the lint's
    beside it — kc's "nothing ran" unless given, as KcExitLoop's lint
    answers unscripted, and waived with a waived test."""
    lint = lint or ("waived" if outcome == "waived" else "nothing_ran")
    return {"project": name, "cmd": " ".join(component_argv(name)),
            "outcome": outcome,
            "lint": {"cmd": " ".join(lint_argv(name)), "outcome": lint}}


def touched_gate_run(tmp, script, gate_rcs, touched, target="frontend",
                     rulings=(), components=split_components, setup=None):
    """One phase on `target` whose diff touches the files `touched`, gated
    by the driver's own gate over scripted kc exit codes."""
    slice_dir, repo = make_slice(tmp, phases=[("1", "First phase", target)])
    if rulings:
        ruled_plan(slice_dir, *rulings,
                   body=phase_section("1", "First phase", target))
    r = KcExitLoop(slice_dir, script, repo_root=repo, gate_rcs=gate_rcs)
    r.fake_git.diff_files = "\n".join(touched)
    if setup is not None:
        setup(r)
    with patched(run_loop, load_project_dirs=components):
        code = run_to_exit(r)
    return slice_dir, repo, r, code


def reviewer_prompt(loop):
    return next(p for role, p in loop.prompts
                if role == "code-reviewer").replace("\n", " ")


def gate_diffs(loop):
    """The `diff --name-only` calls the phase gate made for its touched
    components — `<base>..HEAD`, where the reviewer's secrets scan reads
    `<base>..<sha>`."""
    return [c for _, c in loop.fake_git.calls
            if c[:3] == ("diff", "--name-only", "--no-renames")
            and c[-1].endswith("..HEAD")]


def test_a_component_gate_runs_every_component_its_diff_touches():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo, r, code = touched_gate_run(
            tmp, [V["exec_done"], V["review_signoff"], *TAIL], [0, 0, 0],
            ["frontend/src/App.tsx", "backend/app/api.py",
             "backend/worker/job.py", "backend/worker/test_job.py"])
        assert code == 0 and not r.script
        # the Target first, then each touched component in manifest order —
        # a file is the deepest component's that holds it, from the phase's
        # own tree
        assert [(argv, cwd) for argv, cwd, _ in r.phase_gate_runs] == [
            (component_argv("frontend"), repo),
            (component_argv("backend"), repo),
            (component_argv("worker"), repo)]
        state = load_state(slice_dir)
        ps = state["phases"]["1"]
        assert ps["gate_cmd"] == "kc project test --project frontend"
        assert ps["gate_projects"] == [gate_entry("frontend", "green"),
                                       gate_entry("backend", "green"),
                                       gate_entry("worker", "green")]
        # one gate run, one history row, one log holding every command
        assert [h["outcome"] for h in state["history"]
                if h["role"] == "gate"] == ["green"]
        log = Path(ps["gate_green_log"]).read_text()
        assert log.index("--project frontend: exit 0") < log.index(
            "=== the phase's diff touches backend: "
            "`kc project test --project backend` ===") \
            < log.index("--project backend: exit 0") \
            < log.index("--project worker: exit 0")
        prompt = reviewer_prompt(r)
        assert ("ran GREEN on this exact commit "
                f"({r.fake_git.head[:12]}): `kc project test --project "
                "frontend`, `kc project test --project backend`, `kc project "
                f"test --project worker` in {repo} — with full output in "
                f"{ps['gate_green_log']}. It covers frontend, backend, "
                "worker: the phase's Target and every project its diff "
                "touches. The tests pass; that is") in prompt
        assert "does not cover" not in prompt
        writer = next(p for role, p in r.prompts
                      if role == "code-writer").replace("\n", " ")
        assert ("which runs the driver's own gate: `kc project test --project "
                "frontend` and `kc project lint --project frontend`, and both "
                "for every other component the phase's diff touches.") \
            in writer
        narration = (slice_dir / "log.txt").read_text()
        assert ("gate #1 running (kc project test --project frontend, then "
                "kc project lint --project frontend), and for the components "
                "the phase's diff touches: backend, worker") in narration
        assert ("kc project test --project frontend GREEN; kc project test "
                "--project backend GREEN; kc project test --project worker "
                "GREEN)") in narration


def test_a_red_touched_component_fails_the_gate_into_a_fix_round_naming_it():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo, r, code = touched_gate_run(
            tmp, [V["exec_done"], V["exec_done"], V["review_signoff"], *TAIL],
            [0, 1, 0, 0], ["frontend/src/App.tsx", "backend/app/api.py"])
        assert code == 0 and not r.script
        state = load_state(slice_dir)
        ps = state["phases"]["1"]
        assert ps["gate_fix_rounds"] == 1
        gates = [h for h in state["history"] if h["role"] == "gate"]
        assert [h["outcome"] for h in gates] == ["red", "green"]
        # the red row's summary is the red command's, not the Target's
        assert gates[0]["summary"] == "kc project test --project backend: " \
            "exit 1"
        writers = [p for role, p in r.prompts if role == "code-writer"]
        assert ("The gate went red on `kc project test --project backend`; "
                "its output is in") in writers[1].replace("\n", " ")
        reviews = [p for role, p in r.prompts if role == "code-reviewer"]
        assert len(reviews) == 1, "the review came after the fix round's green"
    # every touched component runs whatever the Target did, so every red is
    # known to the fix round
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo, r, code = touched_gate_run(
            tmp, [V["exec_done"], V["exec_done"], V["review_signoff"], *TAIL],
            [1, 1, 0, 0], ["frontend/src/App.tsx", "backend/app/api.py"])
        assert code == 0
        assert [argv for argv, _, _ in r.phase_gate_runs] == [
            component_argv("frontend"), component_argv("backend")] * 2
        writers = [p for role, p in r.prompts if role == "code-writer"]
        assert ("The gate went red on `kc project test --project frontend`, "
                "`kc project test --project backend`;") \
            in writers[1].replace("\n", " ")


def test_a_touched_component_with_no_tests_is_named_not_covered_never_red():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo, r, code = touched_gate_run(
            tmp, [V["exec_done"], V["review_signoff"], *TAIL], [0, 3],
            ["frontend/src/App.tsx", "backend/app/api.py"])
        assert code == 0 and not r.script, "no fix round was spawned"
        state = load_state(slice_dir)
        ps = state["phases"]["1"]
        assert ps["gate_fix_rounds"] == 0
        assert ps["gate_green_commit"] == r.fake_git.head
        assert ps["gate_projects"] == [gate_entry("frontend", "green"),
                                       gate_entry("backend", "nothing_ran")]
        assert [h["outcome"] for h in state["history"]
                if h["role"] == "gate"] == ["green"]
        prompt = reviewer_prompt(r)
        assert ("`kc project test --project frontend` in "
                f"{repo} — with full output in") in prompt
        assert "`kc project test --project backend` in" not in prompt
        assert "It covers frontend: the phase's Target" in prompt
        assert ("The gate does not cover backend (defines no tests): their "
                "test state is unverified by the driver — say so in your "
                "review where it bears on a finding, and probe it with "
                "targeted runs.") in prompt
    # nothing ran anywhere: the gate ran nothing, and says so of every one
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo, r, code = touched_gate_run(
            tmp, [V["exec_done"], V["review_signoff"], *TAIL], [3, 3, 3, 3],
            ["frontend/src/App.tsx", "backend/app/api.py"])
        assert code == 0 and not r.script
        ps = load_state(slice_dir)["phases"]["1"]
        assert ps["gate_green_commit"] is None
        assert ps["gate_nothing_ran_commit"] == r.fake_git.head
        assert ("`kc project test --project frontend`, `kc project test "
                f"--project backend` in {repo} ran nothing on this exact "
                "commit") in reviewer_prompt(r)
        assert "frontend, backend defines no tests — proceeding" \
            in (slice_dir / "log.txt").read_text()


def test_a_file_outside_every_component_is_roots():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo, r, code = touched_gate_run(
            tmp, [V["exec_done"], V["review_signoff"], *TAIL], [0, 3],
            ["frontend/src/App.tsx", "README.md"])
        assert code == 0 and not r.script
        assert [argv for argv, _, _ in r.phase_gate_runs] == [
            component_argv("frontend"), component_argv("root")]
        ps = load_state(slice_dir)["phases"]["1"]
        assert ps["gate_projects"] == [gate_entry("frontend", "green"),
                                       gate_entry("root", "nothing_ran")]
        assert "The gate does not cover root (defines no tests)" \
            in reviewer_prompt(r)
    # a manifest that lists no root: nothing gates such a file, and the
    # log says so rather than asking kc for a component it does not have

    def rootless(cwd):
        components = split_components(cwd)
        del components["root"]
        return components

    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo, r, code = touched_gate_run(
            tmp, [V["exec_done"], V["review_signoff"], *TAIL], [0],
            ["frontend/src/App.tsx", "README.md"], components=rootless)
        assert code == 0
        assert [argv for argv, _, _ in r.phase_gate_runs] == [
            component_argv("frontend")]
        assert ("the phase's diff touches files outside every component and "
                "kc lists no root — no gate covers them") \
            in (slice_dir / "log.txt").read_text()


def test_a_gate_ruling_waives_a_touched_component_unrun():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo, r, code = touched_gate_run(
            tmp, [V["exec_done"], V["review_signoff"], *TAIL], [0],
            ["frontend/src/App.tsx", "backend/app/api.py"],
            rulings=["gate backend — Jenkins validation build — suites need "
                     "Postgres"])
        assert code == 0 and not r.script
        assert [argv for argv, _, _ in r.phase_gate_runs] == [
            component_argv("frontend")]
        state = load_state(slice_dir)
        ps = state["phases"]["1"]
        assert ps["gate_projects"] == [gate_entry("frontend", "green"),
                                       gate_entry("backend", "waived")]
        prompt = reviewer_prompt(r)
        assert "It covers frontend: the phase's Target" in prompt
        assert ("The gate does not cover backend (waived by plan.md's `## "
                "Driver rulings`): their test state is unverified by the "
                "driver") in prompt
        narration = (slice_dir / "log.txt").read_text()
        assert ("test gate for backend (the phase's diff touches it) waived "
                "by plan.md's `## Driver rulings` (substitute: Jenkins "
                "validation build) — not run") in narration
        assert "Gate waived by ruling: backend — Jenkins validation build" \
            in entries_in_full(slice_dir)
        assert state["rulings_reported"] == ["gate backend"]


def test_a_waived_target_runs_none_of_the_components_its_diff_touches():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo, r, code = touched_gate_run(
            tmp, [V["exec_done"], V["review_signoff"], *TAIL], [1] * 4,
            ["frontend/src/App.tsx", "backend/app/api.py"],
            rulings=["gate frontend — Jenkins validation build — suites "
                     "need Postgres"])
        assert code == 0 and not r.script
        assert r.phase_gate_runs == [] and gate_diffs(r) == []
        ps = load_state(slice_dir)["phases"]["1"]
        assert ps["gate_projects"] is None
        prompt = reviewer_prompt(r)
        assert ("The driver did not run the test gate on this commit: "
                "plan.md's `## Driver rulings` waives it for frontend") \
            in prompt
        assert "does not cover" not in prompt


def test_a_whole_repo_target_gates_no_touched_component():
    touched = ["frontend/src/App.tsx", "backend/app/api.py"]
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo, r, code = touched_gate_run(
            tmp, [V["exec_done"], V["review_signoff"], *TAIL], [0], touched,
            target="root")
        assert code == 0
        assert [argv for argv, _, _ in r.phase_gate_runs] == [ROOT_ARGV]
        assert gate_diffs(r) == []
        # its one entry: root's lint ran nothing, and so did the whole repo's
        assert load_state(slice_dir)["phases"]["1"]["gate_projects"] == [
            {"project": "root", "cmd": " ".join(ROOT_ARGV), "outcome": "green",
             "lint": {"cmd": "kc project lint", "outcome": "nothing_ran"}}]
        prompt = reviewer_prompt(r)
        assert ("`kc project test --project root` in "
                f"{repo} — with full output in") in prompt
        assert "It covers" not in prompt
    with tempfile.TemporaryDirectory() as tmp:
        sib = make_sibling(tmp)
        slice_dir, repo, r, code = touched_gate_run(
            tmp, [V["exec_done"], V["review_signoff"], *TAIL], [0], touched,
            target="../Sibling")
        assert code == 0
        assert [(argv, cwd) for argv, cwd, _ in r.phase_gate_runs] == [
            (BARE_ARGV, sib)]
        assert [(argv, cwd) for argv, cwd, _ in r.phase_lint_runs] == [
            (BARE_LINT_ARGV, sib)]
        assert gate_diffs(r) == []
        assert load_state(slice_dir)["phases"]["1"]["gate_projects"] == [
            {"project": "../Sibling", "cmd": "kc project test",
             "outcome": "green",
             "lint": {"cmd": "kc project lint", "outcome": "nothing_ran"}}]
        assert "It covers" not in reviewer_prompt(r)


def test_the_gate_takes_its_components_from_the_reviews_merge_base():
    """The diff the gate reads its components from is the range the reviewer
    is handed — and, after a rebase onto a moved base, the range as the
    rebase re-took it, which the merge's re-gate reads."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo, r, code = touched_gate_run(
            tmp, [V["exec_done"], V["review_signoff"], *TAIL], [],
            ["frontend/src/App.tsx", "backend/app/api.py"],
            setup=lambda loop: (
                moved_base(loop, "2"),
                setattr(loop.fake_git, "merge_base", "mb-before"),
                setattr(loop.fake_git, "rebased_merge_base", "mb-after")))
        assert code == 0 and not r.script
        assert "git diff mb-before..HEAD on branch phase/074-P1" \
            in reviewer_prompt(r)
        assert [c[-1] for c in gate_diffs(r)] == ["mb-before..HEAD",
                                                 "mb-after..HEAD"]
        # both the first gate and the merge's re-gate took backend in
        assert [argv for argv, _, _ in r.phase_gate_runs] == [
            component_argv("frontend"), component_argv("backend")] * 2
        ps = load_state(slice_dir)["phases"]["1"]
        assert ps["landed"]["base"] == "mb-after"
        assert ps["gate_green_commit"] == "new222"
        # the driver's own rebase narrates itself, never as a writer's move
        assert "merge base moved" not in (slice_dir / "log.txt").read_text()


# -- a writer that moves the merge base (AIWF-104) ----------------------------
#
# PilotApp slice 020 P3: the writer rebased its branch onto a moved base inside
# its round, and the driver, still on the merge base it took when the phase
# began, gated the frontend suite of the base's own commits — red, and the
# writer handed back blocked. The driver re-takes the merge base at every read.

OLD_MB = "7bfad05c1234" + "5" * 28
NEW_MB = "9fab4cb01234" + "6" * 28
MOVED_LINE = ("[P1] merge base moved 7bfad05c1234 → 9fab4cb01234 — "
              "phase/074-P1 was rebased onto or merged main; the phase's "
              "range is re-taken")


def moves_the_merge_base(to, head=None):
    """A code-writer step's effect: it rebased its branch onto a moved base,
    or merged the base into it — the branch's merge base is now `to`, and
    its head `head` where given."""
    def effect(loop):
        loop.fake_git.merge_base = to
        if head is not None:
            loop.fake_git.head = head
    return effect


def test_a_writer_that_moves_the_merge_base_moves_the_phases_range():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo, r, code = touched_gate_run(
            tmp, [("code-writer", DONE, moves_the_merge_base(NEW_MB)),
                  V["review_signoff"], *TAIL], [],
            ["frontend/src/App.tsx", "backend/app/api.py"],
            setup=lambda loop: setattr(loop.fake_git, "merge_base", OLD_MB))
        assert code == 0 and not r.script
        # the gate's touched components, the review and the landed record
        # all read the range from the merge base the writer left
        assert [c[-1] for c in gate_diffs(r)] == [f"{NEW_MB}..HEAD"]
        prompt = reviewer_prompt(r)
        assert f"git diff {NEW_MB}..HEAD on branch phase/074-P1" in prompt
        assert OLD_MB not in prompt
        ps = load_state(slice_dir)["phases"]["1"]
        assert ps["landed"]["base"] == NEW_MB
        assert ps["reviewed_base"] == NEW_MB
        # the spec the writer's wrapper read named the base branch alone
        assert gate_spec(r)["base"] == "main"
        log = (slice_dir / "log.txt").read_text()
        assert log.count(MOVED_LINE) == 1, log
        # the first read, when the phase began, logged nothing
        assert log.index("[P1] start (") < log.index(MOVED_LINE) \
            < log.index("[P1] gate #1 running (")


def test_a_review_after_the_merge_base_moved_reads_the_whole_range():
    """A delta review reads the fix range against the head the last round
    read — but a branch rebased onto a moved base rewrote every commit that
    round read, so the round after the move is a full review, from the new
    merge base, and banks the base it read beside the head."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r = ScriptedLoop(slice_dir, [
            V["exec_done"], V["review_issues"],
            ("code-writer", DONE, moves_the_merge_base(NEW_MB, head="head2")),
            V["review_signoff"], *TAIL], repo_root=repo)
        r.fake_git.merge_base = OLD_MB
        assert run_to_exit(r) == 0 and not r.script
        first, second = (" ".join(p.split()) for p in reviews_of(r))
        assert first.startswith("Review the complete branch diff")
        assert second.startswith(
            "Review the complete branch diff for phase P1 of slice "
            f"074_test_slice (review round 2): git diff {NEW_MB}..HEAD on "
            "branch phase/074-P1")
        assert OLD_MB not in second and "abc123" not in second
        # the secrets scan read the whole range alone, never a fix range
        scans = [c[3] for _, c in r.fake_git.calls
                 if c[:3] == ("diff", "--name-only", "--no-renames")]
        assert scans == [f"{OLD_MB}..abc123", f"{NEW_MB}..head2"]
        ps = load_state(slice_dir)["phases"]["1"]
        assert (ps["reviewed_head"], ps["reviewed_base"]) == ("head2", NEW_MB)
        log = (slice_dir / "log.txt").read_text()
        assert ("[P1] review round 2 reads the whole range — the merge base "
                "moved since round 1 (7bfad05c1234 → 9fab4cb01234)") in log
        assert MOVED_LINE in log
    # the merge base stood still: the round is the delta review it was
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)

        def move_head(loop):
            loop.fake_git.head = "head2"

        r = ScriptedLoop(slice_dir, [
            V["exec_done"], V["review_issues"],
            ("code-writer", DONE, move_head),
            V["review_signoff"], *TAIL], repo_root=repo)
        r.fake_git.merge_base = OLD_MB
        assert run_to_exit(r) == 0 and not r.script
        delta = " ".join(reviews_of(r)[1].split())
        assert delta.startswith("Re-review phase P1")
        assert "git diff abc123..HEAD" in delta
        ps = load_state(slice_dir)["phases"]["1"]
        assert (ps["reviewed_head"], ps["reviewed_base"]) == ("head2", OLD_MB)
        log = (slice_dir / "log.txt").read_text()
        assert "reads the whole range" not in log
        assert "merge base moved" not in log


def test_a_phase_with_no_reviewed_base_on_record_reviews_as_it_always_did():
    """A phase begun on a plugin before AIWF-104 banked no `reviewed_base`:
    its next round is the delta review it would have been, whatever the
    merge base is now, and it banks the base it read."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        state = resume_state(PROJECT)
        state["phases"]["1"].update(review_rounds=1, reviewed_head="old111")
        (slice_dir / "state.json").write_text(json.dumps(state))
        r = ScriptedLoop(slice_dir, [V["review_signoff"], *TAIL],
                         resume=True, repo_root=repo)
        r.fake_git.branches.add("phase/074-P1")
        r.fake_git.merge_base = NEW_MB
        assert run_to_exit(r) == 0 and not r.script
        review = " ".join(reviews_of(r)[0].split())
        assert review.startswith("Re-review phase P1 of slice 074_test_slice "
                                 "(review round 2)")
        assert "git diff old111..HEAD" in review
        assert load_state(slice_dir)["phases"]["1"]["reviewed_base"] == NEW_MB
        assert "reads the whole range" not in \
            (slice_dir / "log.txt").read_text()


def test_a_shared_sibling_components_gate_takes_touched_components_in_its_worktree():
    with tempfile.TemporaryDirectory() as tmp:
        sib = make_sibling(tmp, name="Shared")

        def lists(cwd):
            cwd = Path(cwd)
            return (split_components(cwd) if cwd.name != "repo"
                    else {PROJECT: cwd})

        slice_dir, repo = make_slice(tmp, phases=[("1", "Web", "frontend")])
        r = KcExitLoop(slice_dir, [V["exec_done"], V["review_signoff"],
                                   *TAIL], repo_root=repo)
        r.fake_git.diff_files = "frontend/src/App.tsx\nbackend/app/api.py"
        work = r.worktree_root / "Shared" / "074-P1"
        with patched(run_loop, load_project_dirs=lists,
                     shared_repo_dirs=lambda: {sib.resolve()}):
            assert run_to_exit(r) == 0
        assert [(argv, cwd) for argv, cwd, _ in r.phase_gate_runs] == [
            (component_argv("frontend"), work),
            (component_argv("backend"), work)]
        assert [root for root, c in r.fake_git.calls
                if c[:3] == ("diff", "--name-only", "--no-renames")
                and c[-1].endswith("..HEAD")] == [work]
        assert "It covers frontend, backend: the phase's Target" \
            in reviewer_prompt(r)


def test_a_gate_with_no_projects_on_record_reads_as_it_always_did():
    """A phase begun on a plugin before AIWF-91 has no `gate_projects`: the
    reviewer's line and the fix round's are the Target's command alone."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r = ScriptedLoop(slice_dir, [], repo_root=repo)
        target = run_loop.ResolvedTarget(
            PROJECT, "project", Path(repo),
            ["kc", "project", "test", "--project", PROJECT], Path(repo))
        old = {"gate_green_commit": "deadbeefcafe0",
               "gate_green_log": "/g/gate_r1.log",
               "gate_cmd": f"kc project test --project {PROJECT}"}
        line = r._gate_line(old, "deadbeefcafe0", target)
        assert line.startswith(
            "The deterministic test gate ran GREEN on this exact commit "
            f"(deadbeefcafe):\n`kc project test --project {PROJECT}` in "
            f"{repo} — with full output in /g/gate_r1.log. The tests\n"
            "pass; that is an established input to your review")
        assert "It covers" not in line and "does not cover" not in line
        # an entry off-shape is no record either
        torn = dict(old, gate_projects=[{"project": PROJECT}])
        assert r._gate_line(torn, "deadbeefcafe0", target) == line
        assert r._gate_line(dict(old, gate_projects=None), "deadbeefcafe0",
                            target) == line
        nothing = {"gate_nothing_ran_commit": "deadbeefcafe0",
                   "gate_cmd": old["gate_cmd"]}
        assert r._gate_line(nothing, "deadbeefcafe0", target).startswith(
            f"`kc project test --project {PROJECT}` in {repo} ran nothing on "
            "this exact commit (deadbeefcafe):\nthe target defines no tests")
        assert r._red_cmds({"gate_cmd": "kc project test"}, target) \
            == "`kc project test`"
        assert r._red_cmds({}, target) \
            == f"`kc project test --project {PROJECT}`"
        # a state.json from before the key gets it as None
        r.state = {"phases": {"1": {"status": "in_progress"}}}
        assert r._phase_state("1")["gate_projects"] is None


# -- the writer's gate run, reused as the driver's (AIWF-93) -------------------
#
# The code-writer runs the phase gate before it hands back, and the driver ran
# the same commands again on the same tree: on PilotApp, 75 % of driver gates
# re-ran a green the writer had just seen. The writer now runs it through the
# driver's `gate` wrapper, which records what it ran and on what tree, and the
# driver replays a run it can prove stands for its own gate — and otherwise
# gates exactly as before.

TREE = "7ee0" * 10        # what a stubbed content_tree answers
OTHER_TREE = "0e1d" * 10
DONE = {"outcome": "done", "summary": "built"}


def outputs_of(loop, pid="1"):
    return loop.slice_dir / "phases" / f"P{pid}"


def gate_spec(loop, pid="1"):
    return json.loads((outputs_of(loop, pid) / "gate_spec.json").read_text())


def writer_record(spec, ran, start=TREE, end=TREE, **over):
    """What the `gate` wrapper records over `spec` for a run of `ran` —
    (argv, rc) pairs, each with the output KcExitLoop's kc writes — on a tree
    that was `start` when it began and `end` when it finished; `over` sets
    any key outright."""
    record = {"phase": spec["phase"], "round": spec["round"],
              "work_root": spec["work_root"], "gate_cwd": spec["gate_cwd"],
              "start_tree": start, "end_tree": end,
              "started": "2026-10-24T09:00:00+02:00",
              "finished": "2026-10-24T09:01:00+02:00",
              "commands": [{"argv": list(argv), "rc": rc_,
                            "output": f"{' '.join(argv)}: exit {rc_}\n"}
                           for argv, rc_ in ran],
              "outcome": "green"}
    record.update(over)
    return record


def ran_gate(*commands, text=None, **over):
    """A code-writer step's effect: it ran the gate through the wrapper,
    which recorded `commands` for the round the spec names — or left `text`
    in the record instead."""
    def effect(loop):
        spec = gate_spec(loop)
        path = outputs_of(loop) / f"writer_gate_r{spec['round']}.json"
        path.write_text(text if text is not None else json.dumps(
            writer_record(spec, commands, **over)))
    return effect


def wrote_gate(*commands, **over):
    """A code-writer step that ran the gate through the wrapper."""
    return ("code-writer", DONE, ran_gate(*commands, **over))


def with_lint(argv, rc_, lint_rc=3):
    """A gate's test command run with exit code `rc_`, and the lint the
    wrapper runs beside it (AIWF-105) — kc's "nothing ran" unless given:
    two (argv, rc) pairs of a writer record."""
    return (argv, rc_), (run_loop.lint_twin(argv), lint_rc)


def tree_is(tree):
    return patched(run_loop, content_tree=lambda root: tree)


def gate_rows(slice_dir):
    return [h for h in load_state(slice_dir)["history"] if h["role"] == "gate"]


def reused_header(record, tree=TREE):
    return (f"=== the writer's run of this gate, reused: {record} — the tree "
            f"({tree}) is the one it ran on, unchanged since it began; its "
            "output follows ===\n")


def test_a_green_writer_run_on_the_tree_handed_back_is_the_drivers_gate():
    app = component_argv(PROJECT)
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r = KcExitLoop(slice_dir, [wrote_gate(*with_lint(app, 0)),
                                   V["review_signoff"], *TAIL], repo_root=repo)
        with tree_is(TREE):
            assert run_to_exit(r) == 0
        assert not r.script
        assert r.phase_gate_order == [], "the driver ran no suite of its own"
        record = outputs_of(r) / "writer_gate_r1.json"
        rows = gate_rows(slice_dir)
        assert [(h["outcome"], h.get("reused")) for h in rows] == [
            ("green", str(record))]
        assert rows[0]["summary"] == f"{' '.join(app)}: exit 0"
        ps = load_state(slice_dir)["phases"]["1"]
        assert ps["gate_runs"] == 1
        assert ps["gate_green_commit"] == r.fake_git.head
        assert ps["gate_cmd"] == " ".join(app)
        assert ps["gate_projects"] == [gate_entry(PROJECT, "green")]
        lint = " ".join(lint_argv(PROJECT))
        assert Path(ps["gate_green_log"]).read_text() == (
            reused_header(record) + f"{' '.join(app)}: exit 0\n"
            f"\n=== `{lint}` from {repo} ===\n{lint}: exit 3\n")
        assert ("The deterministic test gate ran GREEN on this exact commit "
                f"({r.fake_git.head[:12]}): `{' '.join(app)}` in {repo} — "
                f"with full output in {ps['gate_green_log']}") \
            in reviewer_prompt(r)
        narration = (slice_dir / "log.txt").read_text()
        assert ("[P1] gate #1 reusing the writer's run (writer_gate_r1.json) "
                f"— tree {TREE[:12]} unchanged since it began\n") in narration
        assert "gate #1 running" not in narration
        assert "[P1] gate #1 → GREEN" in narration


def test_a_reused_gate_inlines_kcs_full_output_as_a_run_does():
    app = component_argv(PROJECT)
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        full = kc_full_log(tmp, "test-1.log", "every line kc ran\n")

        def effect(loop):
            spec = gate_spec(loop)
            record = writer_record(spec, with_lint(app, 0))
            record["commands"][0]["output"] += f"full output: {full}\n"
            (outputs_of(loop) / "writer_gate_r1.json").write_text(
                json.dumps(record))

        r = KcExitLoop(slice_dir, [("code-writer", DONE, effect),
                                   V["review_signoff"], *TAIL],
                       repo_root=repo)
        with tree_is(TREE):
            assert run_to_exit(r) == 0
        log = Path(load_state(slice_dir)["phases"]["1"]["gate_green_log"])
        assert (f"full output: {full}\n\n=== kc's full output ({full}) ===\n"
                "every line kc ran\n\n=== `kc project lint") in log.read_text()


def test_a_reused_touched_gate_records_what_a_run_of_it_would():
    touched = ["frontend/src/App.tsx", "backend/app/api.py"]
    frontend, backend = component_argv("frontend"), component_argv("backend")
    with tempfile.TemporaryDirectory() as tmp:
        real_dir, real_repo, real, code = touched_gate_run(
            tmp, [V["exec_done"], V["review_signoff"], *TAIL], [0, 0],
            touched)
        assert code == 0 and len(real.phase_gate_runs) == 2
        real_ps = load_state(real_dir)["phases"]["1"]
        real_log = Path(real_ps["gate_green_log"]).read_text()
    with tempfile.TemporaryDirectory() as tmp, tree_is(TREE):
        slice_dir, repo, r, code = touched_gate_run(
            tmp, [wrote_gate(*with_lint(frontend, 0), *with_lint(backend, 0)),
                  V["review_signoff"], *TAIL], [], touched)
        assert code == 0 and not r.script
        assert r.phase_gate_order == []
        ps = load_state(slice_dir)["phases"]["1"]
        assert ps["gate_projects"] == real_ps["gate_projects"] == [
            gate_entry("frontend", "green"), gate_entry("backend", "green")]
        assert ps["gate_cmd"] == real_ps["gate_cmd"]
        # the log is the real run's, laid out by the same code, under the
        # reuse's header — its own repo where a header names one
        record = outputs_of(r) / "writer_gate_r1.json"
        assert Path(ps["gate_green_log"]).read_text() \
            == reused_header(record) + real_log.replace(str(real_repo),
                                                        str(repo))
        assert ("It covers frontend, backend: the phase's Target and every "
                "project its diff touches.") in reviewer_prompt(r)
        assert ("gate #1 reusing the writer's run (writer_gate_r1.json) — "
                f"tree {TREE[:12]} unchanged since it began, and for the "
                "components the phase's diff touches: backend") \
            in (slice_dir / "log.txt").read_text()
    # a component a gate ruling waives is in no run, the writer's or the
    # driver's: the record without it is the gate
    with tempfile.TemporaryDirectory() as tmp, tree_is(TREE):
        slice_dir, repo, r, code = touched_gate_run(
            tmp, [wrote_gate(*with_lint(frontend, 0)), V["review_signoff"],
                  *TAIL], [],
            touched, rulings=["gate backend — Jenkins validation build — "
                              "suites need Postgres"])
        assert code == 0 and r.phase_gate_order == []
        ps = load_state(slice_dir)["phases"]["1"]
        assert ps["gate_projects"] == [gate_entry("frontend", "green"),
                                       gate_entry("backend", "waived")]
        assert gate_rows(slice_dir)[0]["reused"]


def test_a_reused_root_gate_that_fell_back_is_the_whole_repos():
    with tempfile.TemporaryDirectory() as tmp, tree_is(TREE):
        slice_dir, repo, r, code = root_gate_run(
            tmp, [wrote_gate((ROOT_ARGV, 3), (BARE_ARGV, 0),
                             (ROOT_LINT_ARGV, 3), (BARE_LINT_ARGV, 3)),
                  V["review_signoff"], *TAIL], [])
        assert code == 0 and not r.script
        assert r.phase_gate_order == []
        ps = load_state(slice_dir)["phases"]["1"]
        assert ps["gate_cmd"] == "kc project test"
        assert ps["gate_green_commit"] == r.fake_git.head
        log = Path(ps["gate_green_log"]).read_text()
        assert log.index("--project root: exit 3") < log.index(
            "=== `kc project test --project root` ran nothing (exit 3) — the "
            "gate is the whole repo: `kc project test` ===") \
            < log.index("kc project test: exit 0")
        assert f"`kc project test` in {repo} — with full output in" \
            in reviewer_prompt(r)
    # nothing ran anywhere is reused as nothing ran
    with tempfile.TemporaryDirectory() as tmp, tree_is(TREE):
        slice_dir, repo, r, code = root_gate_run(
            tmp, [wrote_gate((ROOT_ARGV, 3), (BARE_ARGV, 3),
                             (ROOT_LINT_ARGV, 3), (BARE_LINT_ARGV, 3)),
                  V["review_signoff"], *TAIL], [3, 3])
        assert code == 0 and not r.script
        rows = gate_rows(slice_dir)
        # the merge re-gates: no green on record, and the tree, still the
        # writer's, takes its run again
        assert [(h["outcome"], bool(h.get("reused"))) for h in rows] == [
            ("nothing_ran", True), ("nothing_ran", True)]
        assert r.phase_gate_order == []


def reuse_miss_run(tmp, effect, tree=TREE):
    """One phase on PROJECT whose code-writer leaves `effect` behind, gated
    by the driver's own gate on a tree that hashes to `tree`."""
    slice_dir, repo = make_slice(tmp)
    r = KcExitLoop(slice_dir, [("code-writer", DONE, effect),
                               V["review_signoff"], *TAIL], repo_root=repo)
    with tree_is(tree):
        code = run_to_exit(r)
    return slice_dir, repo, r, code


def assert_gate_ran(slice_dir, r, why=None):
    """The driver ran its own gate, reusing nothing — and logged `why` it
    did not reuse round 1's record, or nothing at all with no `why`."""
    assert r.phase_gate_runs, "the driver ran its own gate"
    assert not any("reused" in h for h in gate_rows(slice_dir))
    narration = (slice_dir / "log.txt").read_text()
    assert "[P1] gate #1 running (" in narration
    assert "reusing the writer's run" not in narration
    if why is None:
        assert "not reused" not in narration
    else:
        assert ("[P1] the writer's gate run (writer_gate_r1.json) not reused "
                f"— {why}; running the gate\n") in narration


def test_a_writer_run_on_another_tree_is_never_the_drivers_gate():
    app = component_argv(PROJECT)
    # the tree changed after the run
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, _, r, code = reuse_miss_run(
            tmp, ran_gate(*with_lint(app, 0)), tree=OTHER_TREE)
        assert code == 0
        assert_gate_ran(slice_dir, r, (
            f"the tree changed after it began (began {TREE[:12]}, ended "
            f"{TREE[:12]}, now {OTHER_TREE[:12]})"))
    # ... or while it ran, and is back where it began
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, _, r, code = reuse_miss_run(
            tmp, ran_gate(*with_lint(app, 0), end=OTHER_TREE))
        assert code == 0
        assert_gate_ran(slice_dir, r, (
            f"the tree changed after it began (began {TREE[:12]}, ended "
            f"{OTHER_TREE[:12]}, now {TREE[:12]})"))

    # a tree git cannot hash is no tree to vouch for
    def unhashable(root):
        raise ValueError("git is gone")

    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r = KcExitLoop(slice_dir, [wrote_gate(*with_lint(app, 0)),
                                   V["review_signoff"], *TAIL], repo_root=repo)
        with patched(run_loop, content_tree=unhashable):
            assert run_to_exit(r) == 0
        assert_gate_ran(slice_dir, r,
                        "the tree could not be hashed: git is gone")


def test_a_writer_run_of_other_commands_or_a_red_is_never_the_drivers_gate():
    app = component_argv(PROJECT)
    frontend, backend = component_argv("frontend"), component_argv("backend")
    touched = ["frontend/src/App.tsx", "backend/app/api.py"]
    # a red is never reused, whatever the tree
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, _, r, code = reuse_miss_run(tmp, ran_gate(*with_lint(app, 1)))
        assert code == 0
        assert_gate_ran(slice_dir, r, f"`{' '.join(app)}` went red")
    # ... and a red lint is a red
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, _, r, code = reuse_miss_run(
            tmp, ran_gate(*with_lint(app, 0, lint_rc=1)))
        assert code == 0
        assert_gate_ran(slice_dir, r,
                        f"`{' '.join(lint_argv(PROJECT))}` went red")
    # a run from before the wrapper linted is not this gate's commands
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, _, r, code = reuse_miss_run(tmp, ran_gate((app, 0)))
        assert code == 0
        assert_gate_ran(slice_dir, r, (
            f"it ran `{' '.join(app)}`, the gate is `{' '.join(app)}`, "
            f"`{' '.join(lint_argv(PROJECT))}`"))
    # the diff touches a component the run did not gate
    with tempfile.TemporaryDirectory() as tmp, tree_is(TREE):
        slice_dir, _, r, code = touched_gate_run(
            tmp, [wrote_gate(*with_lint(frontend, 0)), V["review_signoff"],
                  *TAIL], [0, 0], touched)
        assert code == 0
        assert_gate_ran(slice_dir, r, (
            "it ran `kc project test --project frontend`, `kc project lint "
            "--project frontend`, the gate is `kc project test --project "
            "frontend`, `kc project lint --project frontend`, `kc project "
            "test --project backend`, `kc project lint --project backend`"))
    # the run gated a component a gate ruling waives
    with tempfile.TemporaryDirectory() as tmp, tree_is(TREE):
        slice_dir, _, r, code = touched_gate_run(
            tmp, [wrote_gate(*with_lint(frontend, 0), *with_lint(backend, 0)),
                  V["review_signoff"], *TAIL], [0], touched,
            rulings=["gate backend — Jenkins validation build — suites need "
                     "Postgres"])
        assert code == 0
        assert_gate_ran(slice_dir, r, (
            "it ran `kc project test --project frontend`, `kc project lint "
            "--project frontend`, `kc project test --project backend`, `kc "
            "project lint --project backend`, the gate is `kc project test "
            "--project frontend`, `kc project lint --project frontend`"))
    # a root that ran nothing is the whole repo's gate too
    with tempfile.TemporaryDirectory() as tmp, tree_is(TREE):
        slice_dir, _, r, code = root_gate_run(
            tmp, [wrote_gate((ROOT_ARGV, 3)), V["review_signoff"], *TAIL],
            [3, 0])
        assert code == 0
        assert_gate_ran(slice_dir, r, (
            "it ran `kc project test --project root`, the gate is `kc "
            "project test --project root`, `kc project test`, `kc project "
            "lint --project root`"))


def test_a_writer_record_off_shape_or_from_elsewhere_is_not_reused():
    app = component_argv(PROJECT)
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, _, r, code = reuse_miss_run(tmp, ran_gate(text="{torn"))
        assert code == 0
        assert_gate_ran(slice_dir, r, (
            "unreadable: Expecting property name enclosed in double quotes: "
            "line 1 column 2 (char 1)"))
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, _, r, code = reuse_miss_run(
            tmp, ran_gate((app, 0), commands=[]))
        assert code == 0
        assert_gate_ran(slice_dir, r, "unreadable: `commands` is empty")
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, _, r, code = reuse_miss_run(
            tmp, ran_gate((app, 0), start_tree=None))
        assert code == 0
        assert_gate_ran(slice_dir, r, "unreadable: no `start_tree` of type str")
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo, r, code = reuse_miss_run(
            tmp, ran_gate((app, 0), work_root="/elsewhere"))
        assert code == 0
        assert_gate_ran(slice_dir, r,
                        f"it ran in /elsewhere, the gate runs in {repo}")


def test_only_the_latest_writer_rounds_run_can_be_the_drivers_gate():
    """A review-fix round that never ran the wrapper leaves round 1's record
    the only one: the gate after it runs, and says nothing of round 1's."""
    app = component_argv(PROJECT)
    with tempfile.TemporaryDirectory() as tmp, tree_is(TREE):
        slice_dir, repo = make_slice(tmp)
        r = KcExitLoop(slice_dir, [wrote_gate(*with_lint(app, 0)),
                                   V["review_issues"],
                                   V["exec_done"], V["review_signoff"],
                                   *TAIL], repo_root=repo)
        assert run_to_exit(r) == 0 and not r.script
        rows = gate_rows(slice_dir)
        assert [bool(h.get("reused")) for h in rows] == [True, False]
        assert [argv for argv, _, _ in r.phase_gate_runs] == [app]
        assert gate_spec(r)["round"] == 2
        assert (outputs_of(r) / "writer_gate_r1.json").exists()
        assert not (outputs_of(r) / "writer_gate_r2.json").exists()
        narration = (slice_dir / "log.txt").read_text()
        assert "not reused" not in narration
        assert "[P1] gate #2 running (" in narration


def test_every_code_writer_dispatch_writes_the_gate_spec_with_its_round():
    specs = []

    def seen(loop):
        specs.append(gate_spec(loop))

    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r = ScriptedLoop(slice_dir, [("code-writer", DONE, seen),
                                     ("code-writer", DONE, seen),
                                     V["review_issues"],
                                     ("code-writer", DONE, seen),
                                     V["review_signoff"], *TAIL],
                         repo_root=repo, gates=[False, True, True])
        assert run_to_exit(r) == 0 and not r.script
        assert [s["round"] for s in specs] == [1, 2, 3]
        # the base branch, never a merge base: the wrapper resolves that
        # itself when its run begins (AIWF-104)
        assert specs[0] == {
            "phase": "1", "round": 1, "work_root": str(repo),
            "gate_cwd": str(repo), "base": "main", "spec_check": False,
            "argv": component_argv(PROJECT), "fallback": None,
            "lint_argv": lint_argv(PROJECT), "lint_fallback": None,
            "touched": {"target": PROJECT, "waived": [], "lint_accepted": []}}
        assert all(run_loop.gate_spec_problem(s) is None for s in specs)
    # root: the whole repo after an empty root, and no touched components
    specs.clear()
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp, phases=[("1", "First", "root")])
        r = ScriptedLoop(slice_dir, [("code-writer", DONE, seen),
                                     V["review_signoff"], *TAIL],
                         repo_root=repo)
        with patched(run_loop, load_project_dirs=root_components):
            assert run_to_exit(r) == 0
        assert (specs[0]["argv"], specs[0]["fallback"], specs[0]["touched"]) \
            == (ROOT_ARGV, BARE_ARGV, None)
        assert (specs[0]["lint_argv"], specs[0]["lint_fallback"]) \
            == (ROOT_LINT_ARGV, BARE_LINT_ARGV)
    # a gate ruling's component is named, so the wrapper waives it too
    specs.clear()
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp, phases=[("1", "Web", "frontend")])
        ruled_plan(slice_dir, "gate backend — Jenkins validation build — "
                   "suites need Postgres",
                   body=phase_section("1", "Web", "frontend"))
        r = ScriptedLoop(slice_dir, [("code-writer", DONE, seen),
                                     V["review_signoff"], *TAIL],
                         repo_root=repo)
        with patched(run_loop, load_project_dirs=split_components):
            assert run_to_exit(r) == 0
        assert specs[0]["touched"] == {"target": "frontend",
                                       "waived": ["backend"],
                                       "lint_accepted": []}


def test_a_shared_repos_gate_spec_is_its_worktrees():
    specs = []
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        gated_specs(tmp)
        shared = specs_phase(slice_dir, tmp)
        r = ScriptedLoop(slice_dir, [
            ("code-writer", DONE, lambda loop: specs.append(gate_spec(loop))),
            V["review_signoff"], *TAIL], repo_root=repo)
        work = specs_worktree(r)
        with patched(run_loop, shared_repo_dirs=lambda: {shared}):
            assert run_to_exit(r) == 0
        assert (specs[0]["work_root"], specs[0]["gate_cwd"]) \
            == (str(work), str(work))
        assert (specs[0]["argv"], specs[0]["fallback"], specs[0]["touched"]) \
            == (BARE_ARGV, None, None)


def test_a_phase_with_no_gate_gets_no_gate_spec():
    with tempfile.TemporaryDirectory() as tmp:
        make_sibling(tmp, manifest=False)
        slice_dir, repo = make_slice(tmp)
        written = []
        r = ScriptedLoop(slice_dir, [
            ("code-writer", DONE, lambda loop: written.append(
                (outputs_of(loop) / "gate_spec.json").exists())),
            V["review_signoff"], *TAIL], repo_root=repo)
        (slice_dir / "plan.md").write_text(
            "# plan\n\n" + phase_section("1", "Chart", "../Sibling"))
        assert run_to_exit(r) == 0
        assert written == [False]
        writer = next(p for role, p in r.prompts if role == "code-writer")
        assert " gate " + str(outputs_of(r)) not in writer
        assert "has no kc manifest" in writer


def test_every_code_writer_prompt_names_the_gate_wrapper():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r = ScriptedLoop(slice_dir, [V["exec_done"], V["exec_done"],
                                     V["review_issues"], V["exec_done"],
                                     V["review_signoff"], *TAIL],
                         repo_root=repo, gates=[False, True, True])
        assert run_to_exit(r) == 0 and not r.script
        writers = [p.replace("\n", " ") for role, p in r.prompts
                   if role == "code-writer"]
        assert len(writers) == 3
        assert writers[0].startswith("Execute phase P1")
        assert writers[1].startswith("The gate for phase P1")
        assert ("Each command is fail-fast and terse, so its output ends at "
                "its FIRST failing statement — there may be more behind it."
                ) in writers[1]
        assert writers[2].startswith("You are resolving review findings")
        hint = (f"before handing back — through {wrapper_cmd(outputs_of(r))}, "
                "which runs the driver's own gate: `kc project test --project "
                f"{PROJECT}` and `kc project lint --project {PROJECT}`, and "
                "both for every other component the phase's diff touches. "
                f"{run_loop.GATE_REUSE_HINT}. {run_loop.NOTHING_RAN_HINT}.")
        for writer in writers:
            assert hint in writer
        assert ("checks; run the gate yourself before handing back — "
                "through") in writers[1]
        assert "test your own work" not in writers[1]


# The wrapper itself, over real git: `_tee_exec` is the only seam faked.

class FakeTee:
    """`_tee_exec` scripted by exit code, in order: `rcs` for every command
    but `kc project lint` (0 once spent), `lint_rcs` for those (3 once
    spent, as KcExitLoop's); each call's output passed through to stdout and
    returned, as the real one's is; `effect`, when given, runs once, before
    the first call's output."""

    def __init__(self, rcs=(), effect=None, lint_rcs=()):
        self.rcs = list(rcs)
        self.lint_rcs = list(lint_rcs)
        self.calls = []        # (argv, cwd), lint commands apart
        self.lint_calls = []
        self.order = []        # every call's argv, in the order made
        self.effect = effect

    def __call__(self, argv, cwd):
        if self.effect is not None:
            self.effect()
            self.effect = None
        lint = list(argv[:3]) == ["kc", "project", "lint"]
        if lint:
            rc_ = self.lint_rcs.pop(0) if self.lint_rcs else 3
        else:
            rc_ = self.rcs.pop(0) if self.rcs else 0
        (self.lint_calls if lint else self.calls).append((list(argv), Path(cwd)))
        self.order.append(list(argv))
        output = f"{' '.join(argv)}: exit {rc_}\n"
        sys.stdout.write(output)
        return rc_, output


def wrapper_repo(tmp):
    """A real repo laid out as split_components lays its components out,
    everything committed on main: (the repo, that commit)."""
    repo = Path(tmp) / "repo"
    for rel in ("frontend/App.tsx", "backend/api.py",
                "backend/worker/job.py", "README.md", ".gitignore"):
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("*.log\n" if rel == ".gitignore" else f"{rel}\n")
    sh(repo, "init", "-q", "-b", "main")
    sh(repo, "add", "-A")
    sh(repo, "commit", "-qm", "init")
    return repo, sh(repo, "rev-parse", "HEAD")


def write_spec(tmp, repo, argv, fallback=None, touched=None, round_=1,
               spec_check=False, base="main", lint=None, lint_fallback=None):
    """A gate spec as the driver writes one — without `lint`, as one from
    before the gate linted (AIWF-105) reads."""
    outputs = Path(tmp) / "phases" / "P1"
    outputs.mkdir(parents=True, exist_ok=True)
    spec = outputs / "gate_spec.json"
    spec.write_text(json.dumps({
        "phase": "1", "round": round_, "work_root": str(repo),
        "gate_cwd": str(repo), "base": base, "spec_check": spec_check,
        "argv": argv, "fallback": fallback, "lint_argv": lint,
        "lint_fallback": lint_fallback, "touched": touched}))
    return spec


def run_wrapper(spec, tee, components=split_components):
    with patched(run_loop, _tee_exec=tee, load_project_dirs=components):
        return call(run_loop.cmd_gate, spec=str(spec))


def record_of(spec, round_=1):
    return json.loads((spec.parent / f"writer_gate_r{round_}.json").read_text())


def test_the_gate_wrapper_runs_the_drivers_gate_and_records_the_run():
    with tempfile.TemporaryDirectory() as tmp, plain_git():
        repo, _ = wrapper_repo(tmp)
        # since the base: worker committed on the phase's branch, backend an
        # untracked file and frontend (the Target) an edit — uncommitted
        # work is the gate's too
        sh(repo, "checkout", "-qb", "phase/074-P1")
        (repo / "backend" / "worker" / "job.py").write_text("changed\n")
        sh(repo, "commit", "-qam", "worker")
        (repo / "backend" / "new.py").write_text("new\n")
        (repo / "frontend" / "App.tsx").write_text("changed\n")
        spec = write_spec(tmp, repo, component_argv("frontend"), touched={
            "target": "frontend", "waived": []})
        tee = FakeTee()
        code, out, err = run_wrapper(spec, tee)
        assert code == 0, err
        names = ("frontend", "backend", "worker")
        assert tee.calls == [(component_argv(c), repo) for c in names]
        record = record_of(spec)
        assert run_loop.writer_gate_record_problem(record) is None
        tree = run_loop.content_tree(repo)
        assert record["start_tree"] == record["end_tree"] == tree
        assert (record["phase"], record["round"], record["work_root"],
                record["gate_cwd"], record["outcome"]) \
            == ("1", 1, str(repo), str(repo), "green")
        assert record["commands"] == [
            {"argv": component_argv(c), "rc": 0,
             "output": f"kc project test --project {c}: exit 0\n"}
            for c in names]
        assert out.index(f"=== `kc project test --project frontend` from "
                         f"{repo} ===") \
            < out.index("kc project test --project frontend: exit 0") \
            < out.index("=== the phase's diff touches backend: `kc project "
                        "test --project backend` ===") \
            < out.index("kc project test --project backend: exit 0") \
            < out.index("=== the phase's diff touches worker:")
        record_path = spec.parent / "writer_gate_r1.json"
        assert out.rstrip("\n").endswith(
            f"\n=== gate GREEN on tree {tree[:12]}, recorded in "
            f"{record_path}. Hand back this tree — committing it changes "
            "nothing — and the driver takes this run as its gate; edit "
            "anything first and it runs the gate again. ===")
        # what it vouched for survives the commit
        sh(repo, "add", "-A")
        sh(repo, "commit", "-qm", "P1")
        assert run_loop.content_tree(repo) == tree
        # a component a gate ruling waives is named, not run — and the
        # round's later run replaces its record
        spec = write_spec(tmp, repo, component_argv("frontend"), touched={
            "target": "frontend", "waived": ["backend"]})
        tee = FakeTee()
        code, out, _ = run_wrapper(spec, tee)
        assert code == 0
        assert [argv for argv, _ in tee.calls] == [
            component_argv("frontend"), component_argv("worker")]
        assert ("=== the phase's diff touches backend: `kc project test "
                "--project backend` waived by plan.md's `## Driver rulings` "
                "— not run ===") in out
        assert [c["argv"] for c in record_of(spec)["commands"]] == [
            component_argv("frontend"), component_argv("worker")]


def test_the_gate_wrapper_exits_with_the_gates_outcome():
    with tempfile.TemporaryDirectory() as tmp, plain_git():
        repo, _ = wrapper_repo(tmp)
        (repo / "backend" / "api.py").write_text("changed\n")
        spec = write_spec(tmp, repo, component_argv("frontend"), touched={
            "target": "frontend", "waived": []})
        code, out, _ = run_wrapper(spec, FakeTee([0, 1]))
        assert code == 1
        assert out.rstrip("\n").endswith(
            "\n=== gate RED: `kc project test --project backend` ===")
        assert record_of(spec)["outcome"] == "red"
        # kc's usage error is red here, never a pass
        code, out, _ = run_wrapper(spec, FakeTee([2, 0]))
        assert code == 1
        assert "=== gate RED: `kc project test --project frontend` ===" in out
        code, out, _ = run_wrapper(spec, FakeTee([3, 3]))
        assert code == 3
        assert out.rstrip("\n").endswith(
            "\n=== gate: nothing ran (exit 3) — not red, nothing to fix ===")
        assert record_of(spec)["outcome"] == "nothing_ran"
        code, _, _ = run_wrapper(spec, FakeTee([3, 0]))
        assert code == 0 and record_of(spec)["outcome"] == "green"
        # a file no component holds, where kc lists no root: said, not run

        def rootless(cwd):
            components = split_components(cwd)
            del components["root"]
            return components

        (repo / "README.md").write_text("changed\n")
        tee = FakeTee()
        code, out, _ = run_wrapper(spec, tee, components=rootless)
        assert code == 0
        assert [argv for argv, _ in tee.calls] == [
            component_argv("frontend"), component_argv("backend")]
        assert ("=== the phase's diff touches files outside every component "
                "and kc lists no root — no gate covers them ===") in out


def test_the_gate_wrapper_falls_back_to_the_whole_repo_only_after_an_empty_root():
    with tempfile.TemporaryDirectory() as tmp, plain_git():
        repo, _ = wrapper_repo(tmp)
        spec = write_spec(tmp, repo, ROOT_ARGV, fallback=BARE_ARGV)
        tee = FakeTee([3, 0])
        code, out, _ = run_wrapper(spec, tee)
        assert code == 0
        assert [argv for argv, _ in tee.calls] == [ROOT_ARGV, BARE_ARGV]
        assert ("=== `kc project test --project root` ran nothing (exit 3) — "
                "the gate is the whole repo: `kc project test` ===") in out
        for rcs in ([0], [1]):
            tee = FakeTee(rcs)
            code, _, _ = run_wrapper(spec, tee)
            assert code == rcs[0]
            assert [argv for argv, _ in tee.calls] == [ROOT_ARGV]
        code, out, _ = run_wrapper(spec, FakeTee([3, 1]))
        assert code == 1 and "=== gate RED: `kc project test` ===" in out


def test_a_tree_that_changed_while_the_wrapper_ran_is_recorded_so():
    with tempfile.TemporaryDirectory() as tmp, plain_git():
        repo, _ = wrapper_repo(tmp)
        spec = write_spec(tmp, repo, component_argv(PROJECT))
        start = run_loop.content_tree(repo)
        tee = FakeTee(effect=lambda: (repo / "mid_run.py").write_text("x\n"))
        code, out, _ = run_wrapper(spec, tee)
        assert code == 0
        record = record_of(spec)
        end = run_loop.content_tree(repo)
        assert record["start_tree"] == start != end == record["end_tree"]
        assert out.rstrip("\n").endswith(
            f"\n=== gate GREEN, but the tree changed while it ran "
            f"({start[:12]} → {end[:12]}): the driver will run the gate "
            "again. Run this once more on the finished tree to spare it "
            "that. ===")
        assert "recorded in" not in out


def test_the_gate_wrapper_without_a_usable_spec_runs_and_records_nothing():
    with tempfile.TemporaryDirectory() as tmp, plain_git():
        repo, _ = wrapper_repo(tmp)
        outputs = Path(tmp) / "phases" / "P1"
        outputs.mkdir(parents=True)
        tee = FakeTee()
        code, _, err = run_wrapper(outputs / "gate_spec.json", tee)
        assert code == 2 and err.startswith("gate: cannot read the gate spec")
        for text in ("{torn", json.dumps([1]), json.dumps({"phase": "1"})):
            (outputs / "gate_spec.json").write_text(text)
            code, _, err = run_wrapper(outputs / "gate_spec.json", tee)
            assert code == 2 and err.startswith("gate: "), err
        touched = {"target": "frontend", "waived": []}
        # kc cannot list the components
        spec = write_spec(tmp, repo, component_argv("frontend"),
                          touched=touched)
        code, _, err = run_wrapper(spec, tee,
                                   components=kc_lists(repo="kc is down"))
        assert (code, err) == (2, "gate: kc is down\n")
        # a base branch git does not know: no merge base to read a range from
        for spec_check, touched_ in ((False, touched), (True, None)):
            spec = write_spec(tmp, repo, component_argv("frontend"),
                              touched=touched_, spec_check=spec_check,
                              base="gone")
            code, _, err = run_wrapper(spec, tee)
            assert code == 2 and "git merge-base gone HEAD" in err, err
        # a tree git cannot hash
        (Path(tmp) / "plain").mkdir()
        spec = write_spec(tmp, Path(tmp) / "plain", component_argv(PROJECT))
        code, _, err = run_wrapper(spec, tee)
        assert code == 2 and "git rev-parse" in err
        assert tee.calls == []
        assert not list(outputs.glob("writer_gate_r*.json"))


def test_tee_exec_passes_a_commands_output_through_and_keeps_it():
    with tempfile.TemporaryDirectory() as tmp:
        raw = io.BytesIO()
        out = io.TextIOWrapper(raw, encoding="utf-8")
        argv = [sys.executable, "-c",
                "import os, sys; print(os.getcwd()); "
                "print('to err', file=sys.stderr); sys.exit(3)"]
        with patched(sys, stdout=out):
            print("before", flush=True)
            code, output = run_loop._tee_exec(argv, Path(tmp))
        out.flush()
        assert code == 3
        assert os.path.realpath(tmp) in output and "to err" in output
        assert raw.getvalue().decode() == "before\n" + output


def test_content_tree_is_the_tree_a_commit_of_the_working_tree_makes():
    with tempfile.TemporaryDirectory() as tmp, plain_git():
        repo, _ = wrapper_repo(tmp)
        clean = run_loop.content_tree(repo)
        assert clean == sh(repo, "rev-parse", "HEAD^{tree}")
        index = repo / ".git" / "index"
        before = index.read_bytes()
        (repo / "README.md").write_text("changed\n")
        (repo / "new.py").write_text("new\n")
        dirty = run_loop.content_tree(repo)
        assert dirty != clean
        assert index.read_bytes() == before, "the real index is untouched"
        # an ignored file, or a timestamp, is no part of it
        (repo / "run.log").write_text("noise\n")
        os.utime(repo / "README.md", (0, 0))
        assert run_loop.content_tree(repo) == dirty
        assert index.read_bytes() == before
        sh(repo, "add", "-A")
        sh(repo, "commit", "-qm", "work")
        assert sh(repo, "rev-parse", "HEAD^{tree}") == dirty
        assert run_loop.content_tree(repo) == dirty
        # a linked worktree has an index of its own, and a tree of its own
        work = Path(tmp) / "work"
        sh(repo, "worktree", "add", "-q", "-b", "side", str(work))
        assert run_loop.content_tree(work) == dirty
        (work / "side.py").write_text("side\n")
        work_index = Path(sh(work, "rev-parse", "--git-path", "index"))
        assert work_index.is_absolute()
        before = work_index.read_bytes()
        side = run_loop.content_tree(work)
        assert side != dirty and work_index.read_bytes() == before
        assert run_loop.content_tree(repo) == dirty
        sh(work, "add", "-A")
        sh(work, "commit", "-qm", "side")
        assert sh(work, "rev-parse", "HEAD^{tree}") == side
    # no index yet: what is there, as the first commit will hold it
    with tempfile.TemporaryDirectory() as tmp, plain_git():
        repo = Path(tmp)
        sh(repo, "init", "-q", "-b", "main")
        (repo / "a.py").write_text("a\n")
        first = run_loop.content_tree(repo)
        assert not (repo / ".git" / "index").exists()
        sh(repo, "add", "-A")
        sh(repo, "commit", "-qm", "first")
        assert sh(repo, "rev-parse", "HEAD^{tree}") == first
    # outside git, or nowhere at all: git's own message, never a hash
    with tempfile.TemporaryDirectory() as tmp, plain_git():
        for where in (Path(tmp), Path(tmp) / "gone"):
            try:
                run_loop.content_tree(where)
            except ValueError as e:
                assert "git rev-parse --git-path index" in str(e), e
            else:
                raise AssertionError(f"{where} hashed")


def test_the_drivers_gate_is_the_wrappers_own_run_on_the_tree_handed_back():
    """End to end over real git: the writer runs the wrapper on its spec,
    commits what it ran on, and hands back; the driver replays that run."""
    with tempfile.TemporaryDirectory() as tmp, plain_git():
        slice_dir, repo = make_slice(tmp)
        sh(repo, "init", "-q", "-b", "main")
        sh(repo, "add", "-A")
        sh(repo, "commit", "-qm", "init")
        ran = []

        def works_and_gates(loop):
            (repo / "src.py").write_text("the phase's\n")
            ran.append(call(run_loop.cmd_gate, spec=str(
                outputs_of(loop) / "gate_spec.json")))
            sh(repo, "add", "-A")
            sh(repo, "commit", "-qm", "P1")

        r = KcExitLoop(slice_dir, [("code-writer", DONE, works_and_gates),
                                   V["review_signoff"], *TAIL],
                       repo_root=repo)
        r.fake_git.merge_bases = [sh(repo, "rev-parse", "HEAD")]
        tee = FakeTee()
        with patched(run_loop, _tee_exec=tee):
            assert run_to_exit(r) == 0
        assert ran[0][0] == 0, ran
        assert tee.order == [component_argv(PROJECT), lint_argv(PROJECT)]
        assert r.phase_gate_order == []
        assert gate_rows(slice_dir)[0]["reused"] \
            == str(outputs_of(r) / "writer_gate_r1.json")
        assert load_state(slice_dir)["phases"]["1"]["gate_green_commit"] \
            == r.fake_git.head


# -- the lint beside the test (AIWF-105) ---------------------------------------
#
# PilotApp slices 008 P10 and 020 P9: the phase gate ran frontend's Playwright
# suite alone, so its `pnpm check` (eslint, `tsc -b`, knip) was never gated,
# while the plans said tsc was green at the phase's gate and the reviewer was
# told not to re-run it. Every project the gate tests is linted beside it.

LINT_TOUCHED = ["frontend/src/App.tsx", "backend/app/api.py"]


def linting(*rcs):
    """touched_gate_run's `setup`: the gate's lint commands exit with `rcs`
    in order."""
    return lambda loop: setattr(loop, "lint_rcs", list(rcs))


def test_the_gate_lints_every_project_it_tests():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo, r, code = touched_gate_run(
            tmp, [V["exec_done"], V["review_signoff"], *TAIL], [0, 0],
            LINT_TOUCHED, setup=linting(0, 0))
        assert code == 0 and not r.script
        # each project's test, then its lint: the Target first
        assert [(argv, cwd) for argv, cwd, _ in r.phase_gate_order] == [
            (component_argv("frontend"), repo), (lint_argv("frontend"), repo),
            (component_argv("backend"), repo), (lint_argv("backend"), repo)]
        state = load_state(slice_dir)
        ps = state["phases"]["1"]
        assert ps["gate_projects"] == [gate_entry("frontend", "green", "green"),
                                       gate_entry("backend", "green", "green")]
        # the history row records the run's projects, lint beside test
        rows = [h for h in state["history"] if h["role"] == "gate"]
        assert [h["outcome"] for h in rows] == ["green"]
        assert rows[0]["projects"] == ps["gate_projects"]
        log = Path(ps["gate_green_log"]).read_text()
        marks = [log.index(m) for m in (
            "kc project test --project frontend: exit 0",
            f"=== `kc project lint --project frontend` from {repo} ===",
            "kc project lint --project frontend: exit 0",
            "=== the phase's diff touches backend: `kc project test "
            "--project backend` ===",
            "kc project test --project backend: exit 0",
            "=== the phase's diff touches backend: `kc project lint "
            "--project backend` ===",
            "kc project lint --project backend: exit 0")]
        assert marks == sorted(marks)
        # the reviewer is told both ran clean, and not to re-run either
        assert ("ran GREEN on this exact commit "
                f"({r.fake_git.head[:12]}): `kc project test --project "
                "frontend`, `kc project lint --project frontend`, `kc project "
                "test --project backend`, `kc project lint --project backend` "
                f"in {repo} — with full output in {ps['gate_green_log']}. It "
                "covers frontend, backend: the phase's Target and every "
                "project its diff touches. The tests pass and the lint is "
                "clean; that is an established input to your review, not "
                "something to re-derive. Do not re-run the suite or the lint "
                "to confirm it.") in reviewer_prompt(r)
        assert ("(0s, kc project test --project frontend GREEN; kc project "
                "lint --project frontend GREEN; kc project test --project "
                "backend GREEN; kc project lint --project backend GREEN)") \
            in (slice_dir / "log.txt").read_text()


def test_a_red_lint_is_a_red_gate_and_its_fix_round_names_it():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo, r, code = touched_gate_run(
            tmp, [V["exec_done"], V["exec_done"], V["review_signoff"], *TAIL],
            [0, 0, 0, 0], LINT_TOUCHED, setup=linting(0, 1, 0, 0))
        assert code == 0 and not r.script
        state = load_state(slice_dir)
        assert state["phases"]["1"]["gate_fix_rounds"] == 1
        rows = [h for h in state["history"] if h["role"] == "gate"]
        assert [h["outcome"] for h in rows] == ["red", "green"]
        assert rows[0]["summary"] == "kc project lint --project backend: exit 1"
        assert rows[0]["projects"][1] == gate_entry("backend", "green", "red")
        writers = [p for role, p in r.prompts if role == "code-writer"]
        assert ("The gate went red on `kc project lint --project backend`; "
                "its output is in") in writers[1].replace("\n", " ")
        reviews = [p for role, p in r.prompts if role == "code-reviewer"]
        assert len(reviews) == 1, "the review came after the fix round's green"
    # a red lint reds a gate whose tests ran nothing
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r = KcExitLoop(slice_dir, [V["exec_done"], V["exec_done"],
                                   V["review_signoff"], *TAIL],
                       repo_root=repo, gate_rcs=[3, 3, 3], lint_rcs=[1])
        assert run_to_exit(r) == 0 and not r.script
        assert [h["outcome"] for h in gate_rows(slice_dir)] \
            == ["red", "nothing_ran", "nothing_ran"]
        writers = [p for role, p in r.prompts if role == "code-writer"]
        assert (f"The gate went red on `kc project lint --project {PROJECT}`;"
                in writers[1].replace("\n", " "))


def test_a_lint_that_ran_nothing_is_skipped_and_a_clean_one_proves_no_tests():
    # frontend has no lint to run: not red, not named, not uncovered
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo, r, code = touched_gate_run(
            tmp, [V["exec_done"], V["review_signoff"], *TAIL], [0, 0],
            LINT_TOUCHED, setup=linting(3, 0))
        assert code == 0 and not r.script
        ps = load_state(slice_dir)["phases"]["1"]
        assert ps["gate_fix_rounds"] == 0
        assert ps["gate_green_commit"] == r.fake_git.head
        assert ps["gate_projects"] == [
            gate_entry("frontend", "green", "nothing_ran"),
            gate_entry("backend", "green", "green")]
        prompt = reviewer_prompt(r)
        assert ("`kc project test --project frontend`, `kc project test "
                "--project backend`, `kc project lint --project backend` in "
                f"{repo} — with full output in") in prompt
        assert "lint --project frontend" not in prompt
        assert "does not cover" not in prompt
        assert ("(0s, kc project test --project frontend GREEN; kc project "
                "test --project backend GREEN; kc project lint --project "
                "backend GREEN)") in (slice_dir / "log.txt").read_text()
    # a clean lint over tests that ran nothing proves no tests: the gate ran
    # nothing, and the reviewer is told so
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r = KcExitLoop(slice_dir, [V["exec_done"], V["review_signoff"],
                                   *TAIL],
                       repo_root=repo, gate_rcs=[3, 3], lint_rcs=[0, 0])
        assert run_to_exit(r) == 0 and not r.script
        ps = load_state(slice_dir)["phases"]["1"]
        assert ps["gate_green_commit"] is None
        assert ps["gate_nothing_ran_commit"] == r.fake_git.head
        prompt = reviewer_prompt(r)
        assert (f"`kc project test --project {PROJECT}` in {repo} ran nothing "
                "on this exact commit") in prompt
        assert "GREEN" not in prompt


def test_a_root_target_lints_in_the_same_two_steps_as_it_tests():
    script = [V["exec_done"], V["review_signoff"], *TAIL]
    # root's own lint ran nothing: the whole repo's runs, on its own outcome
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo, r, code = root_gate_run(tmp, script, [0], [3, 0])
        assert code == 0 and not r.script
        assert [argv for argv, _, _ in r.phase_gate_order] == [
            ROOT_ARGV, ROOT_LINT_ARGV, BARE_LINT_ARGV]
        ps = load_state(slice_dir)["phases"]["1"]
        assert ps["gate_projects"] == [
            {"project": "root", "cmd": " ".join(ROOT_ARGV), "outcome": "green",
             "lint": {"cmd": "kc project lint", "outcome": "green"}}]
        log = Path(ps["gate_green_log"]).read_text()
        assert log.index("--project root: exit 3") < log.index(
            "=== `kc project lint --project root` ran nothing (exit 3) — the "
            "gate lints the whole repo: `kc project lint` ===") \
            < log.index("kc project lint: exit 0")
        assert ("`kc project lint --project root` ran nothing — root declares "
                "no lint, so the gate lints the whole repo: `kc project "
                "lint`") in (slice_dir / "log.txt").read_text()
        assert (f"`kc project test --project root`, `kc project lint` in "
                f"{repo} — with full output") in reviewer_prompt(r)
    # root's own lint ran: the whole repo's never does
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo, r, code = root_gate_run(tmp, script, [0], [0])
        assert code == 0
        assert [argv for argv, _, _ in r.phase_gate_order] == [
            ROOT_ARGV, ROOT_LINT_ARGV]
    # the whole repo's lint red: a fix round, told so
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo, r, code = root_gate_run(
            tmp, [V["exec_done"], *script], [3, 0, 3, 0], [3, 1, 3, 0])
        assert code == 0 and not r.script
        assert [h["outcome"] for h in gate_rows(slice_dir)] == ["red", "green"]
        writers = [p for role, p in r.prompts if role == "code-writer"]
        assert "The gate went red on `kc project lint`;" in writers[1]


def test_a_writer_run_that_linted_is_the_drivers_gate_and_names_the_lint():
    app = component_argv(PROJECT)
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r = KcExitLoop(slice_dir, [wrote_gate(*with_lint(app, 0, lint_rc=0)),
                                   V["review_signoff"], *TAIL], repo_root=repo)
        with tree_is(TREE):
            assert run_to_exit(r) == 0
        assert not r.script
        assert r.phase_gate_order == [], "the driver ran nothing itself"
        assert gate_rows(slice_dir)[0]["reused"]
        ps = load_state(slice_dir)["phases"]["1"]
        assert ps["gate_projects"] == [gate_entry(PROJECT, "green", "green")]
        assert (f"`{' '.join(app)}`, `{' '.join(lint_argv(PROJECT))}` in "
                f"{repo} — with full output in") in reviewer_prompt(r)


def test_the_gate_wrapper_lints_beside_every_test_it_runs():
    with tempfile.TemporaryDirectory() as tmp, plain_git():
        repo, _ = wrapper_repo(tmp)
        (repo / "backend" / "api.py").write_text("changed\n")
        touched = {"target": "frontend", "waived": [], "lint_accepted": []}
        spec = write_spec(tmp, repo, component_argv("frontend"),
                          touched=touched, lint=lint_argv("frontend"))
        tee = FakeTee(lint_rcs=[0, 0])
        code, out, _ = run_wrapper(spec, tee)
        assert code == 0
        gate = [component_argv("frontend"), lint_argv("frontend"),
                component_argv("backend"), lint_argv("backend")]
        assert tee.order == gate
        assert [c["argv"] for c in record_of(spec)["commands"]] == gate
        assert out.index(f"=== `kc project lint --project frontend` from "
                         f"{repo} ===") \
            < out.index("=== the phase's diff touches backend: `kc project "
                        "lint --project backend` ===")
        # a red lint reds the gate; one that ran nothing does not, and a
        # clean one over tests that ran nothing is no green
        code, out, _ = run_wrapper(spec, FakeTee(lint_rcs=[0, 1]))
        assert code == 1
        assert out.rstrip("\n").endswith(
            "\n=== gate RED: `kc project lint --project backend` ===")
        assert run_wrapper(spec, FakeTee(lint_rcs=[3, 3]))[0] == 0
        assert run_wrapper(spec, FakeTee([3, 3], lint_rcs=[0, 0]))[0] == 3
        # a component a gate ruling waives: both named, neither run
        spec = write_spec(tmp, repo, component_argv("frontend"), touched={
            "target": "frontend", "waived": ["backend"], "lint_accepted": []},
            lint=lint_argv("frontend"))
        tee = FakeTee()
        code, out, _ = run_wrapper(spec, tee)
        assert code == 0
        assert tee.order == gate[:2]
        assert ("=== the phase's diff touches backend: `kc project test "
                "--project backend` and `kc project lint --project backend` "
                "waived by plan.md's `## Driver rulings` — not run ===") in out
        # root: the whole repo's lint after an empty root's, as for the test
        spec = write_spec(tmp, repo, ROOT_ARGV, fallback=BARE_ARGV,
                          lint=ROOT_LINT_ARGV, lint_fallback=BARE_LINT_ARGV)
        tee = FakeTee(lint_rcs=[3, 0])
        code, out, _ = run_wrapper(spec, tee)
        assert code == 0
        assert tee.order == [ROOT_ARGV, ROOT_LINT_ARGV, BARE_LINT_ARGV]
        assert ("=== `kc project lint --project root` ran nothing (exit 3) — "
                "the gate lints the whole repo: `kc project lint` ===") in out


ACCEPT_BACKEND_LINT = "accept backend lint — red before this slice, ANS-99"


def test_a_lint_an_accept_ruling_covers_is_not_run_at_the_phase_gate():
    """An environment that cannot run a repo's lint gets past the sweep and
    the tool check on accept rulings (Ansible slice 033); the phase gate's
    lint honours them too, or every phase there would red on it."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo, r, code = touched_gate_run(
            tmp, [V["exec_done"], V["review_signoff"], *TAIL], [0, 0],
            LINT_TOUCHED, rulings=[ACCEPT_BACKEND_LINT], setup=linting(0))
        assert code == 0 and not r.script
        assert [argv for argv, _, _ in r.phase_gate_order] == [
            component_argv("frontend"), lint_argv("frontend"),
            component_argv("backend")]
        state = load_state(slice_dir)
        ps = state["phases"]["1"]
        assert ps["gate_fix_rounds"] == 0
        assert ps["gate_green_commit"] == r.fake_git.head
        assert ps["gate_projects"] == [
            gate_entry("frontend", "green", "green"),
            gate_entry("backend", "green", "accepted")]
        assert ("=== the phase's diff touches backend: `kc project lint "
                "--project backend` not run: plan.md's `## Driver rulings` "
                "accepts its red (red before this slice, ANS-99) ===") \
            in Path(ps["gate_green_log"]).read_text()
        assert ("`kc project lint --project backend` not run — plan.md's `## "
                "Driver rulings` accepts its red (red before this slice, "
                "ANS-99)") in (slice_dir / "log.txt").read_text()
        # reported once, the first time it took effect
        assert state["rulings_reported"] == ["accept backend lint"]
        assert "Red row accepted by ruling: backend lint" \
            in entries_in_full(slice_dir)
        prompt = reviewer_prompt(r)
        assert ("It covers frontend, backend: the phase's Target and every "
                "project its diff touches. The lint of `backend` was not run: "
                "plan.md's `## Driver rulings` accepts its red. The tests pass "
                "and the lint is clean; that is") in prompt
        assert "does not cover" not in prompt
    # the Target's own: no lint ran green, so none is called clean
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        ruled_plan(slice_dir, "accept app lint — red before this slice, ANS-99")
        r = KcExitLoop(slice_dir, [V["exec_done"], V["review_signoff"],
                                   *TAIL], repo_root=repo)
        assert run_to_exit(r) == 0 and not r.script
        assert r.phase_lint_runs == []
        ps = load_state(slice_dir)["phases"]["1"]
        assert ps["gate_projects"] == [gate_entry(PROJECT, "green", "accepted")]
        prompt = reviewer_prompt(r)
        assert (f"with full output in {ps['gate_green_log']}. It covers "
                f"{PROJECT}: the phase's Target and every project its diff "
                f"touches. The lint of `{PROJECT}` was not run: plan.md's `## "
                "Driver rulings` "
                "accepts its red. The tests pass; that is an established input "
                "to your review, not something to re-derive. Do not re-run the "
                "suite to confirm it.") in prompt
    # root's whole-repo step is covered by any ruling in the repo
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp, phases=[("1", "First", "root")])
        ruled_plan(slice_dir, "accept app lint — red before this slice, ANS-99",
                   body=phase_section("1", "First", "root"))
        r = KcExitLoop(slice_dir, [V["exec_done"], V["review_signoff"],
                                   *TAIL], repo_root=repo)
        with patched(run_loop, load_project_dirs=root_components):
            assert run_to_exit(r) == 0
        assert [argv for argv, _, _ in r.phase_gate_order] == [
            ROOT_ARGV, ROOT_LINT_ARGV]
        assert load_state(slice_dir)["phases"]["1"]["gate_projects"][0][
            "lint"] == {"cmd": "kc project lint", "outcome": "accepted"}
    # an accept ruling never covers a test at the phase gate
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo, r, code = touched_gate_run(
            tmp, [V["exec_done"], V["exec_done"], V["review_signoff"], *TAIL],
            [0, 1, 0, 0], LINT_TOUCHED,
            rulings=["accept backend test — flaky before this slice, ANS-1"])
        assert code == 0 and not r.script
        assert load_state(slice_dir)["phases"]["1"]["gate_fix_rounds"] == 1


def test_an_accepted_lint_is_in_no_spec_wrapper_run_or_reuse():
    # the Target's: no `lint_argv`, so the wrapper runs its test alone, and
    # the driver takes that run as its gate
    with tempfile.TemporaryDirectory() as tmp, plain_git():
        slice_dir, repo = make_slice(tmp)
        ruled_plan(slice_dir, "accept app lint — red before this slice, ANS-99")
        sh(repo, "init", "-q", "-b", "main")
        sh(repo, "add", "-A")
        sh(repo, "commit", "-qm", "init")
        specs = []

        def works_and_gates(loop):
            specs.append(gate_spec(loop))
            (repo / "src.py").write_text("the phase's\n")
            call(run_loop.cmd_gate, spec=str(
                outputs_of(loop) / "gate_spec.json"))
            sh(repo, "add", "-A")
            sh(repo, "commit", "-qm", "P1")

        r = KcExitLoop(slice_dir, [("code-writer", DONE, works_and_gates),
                                   V["review_signoff"], *TAIL],
                       repo_root=repo)
        r.fake_git.merge_bases = [sh(repo, "rev-parse", "HEAD")]
        tee = FakeTee()
        with patched(run_loop, _tee_exec=tee):
            assert run_to_exit(r) == 0
        assert (specs[0]["lint_argv"], specs[0]["lint_fallback"]) == (None, None)
        assert specs[0]["touched"]["lint_accepted"] == [PROJECT]
        assert tee.order == [component_argv(PROJECT)]
        assert r.phase_gate_order == []
        assert gate_rows(slice_dir)[0]["reused"]
        assert load_state(slice_dir)["phases"]["1"]["gate_projects"] == [
            gate_entry(PROJECT, "green", "accepted")]
    # a touched component's: named in the spec, said and not run by the
    # wrapper, and absent from the record the driver reuses
    with tempfile.TemporaryDirectory() as tmp, plain_git():
        repo, _ = wrapper_repo(tmp)
        (repo / "backend" / "api.py").write_text("changed\n")
        spec = write_spec(tmp, repo, component_argv("frontend"), touched={
            "target": "frontend", "waived": [], "lint_accepted": ["backend"]},
            lint=lint_argv("frontend"))
        tee = FakeTee(lint_rcs=[0])
        code, out, _ = run_wrapper(spec, tee)
        assert code == 0
        assert tee.order == [component_argv("frontend"), lint_argv("frontend"),
                             component_argv("backend")]
        assert out.index("kc project test --project backend: exit 0") \
            < out.index("=== the phase's diff touches backend: `kc project "
                        "lint --project backend` not run: plan.md's `## Driver "
                        "rulings` accepts its red ===")
    frontend, backend = component_argv("frontend"), component_argv("backend")
    with tempfile.TemporaryDirectory() as tmp, tree_is(TREE):
        slice_dir, repo, r, code = touched_gate_run(
            tmp, [wrote_gate(*with_lint(frontend, 0), (backend, 0)),
                  V["review_signoff"], *TAIL], [], LINT_TOUCHED,
            rulings=[ACCEPT_BACKEND_LINT])
        assert code == 0 and not r.script
        assert r.phase_gate_order == [], "the writer's run is the gate"
        assert load_state(slice_dir)["phases"]["1"]["gate_projects"][1] \
            == gate_entry("backend", "green", "accepted")


def test_a_gate_projects_record_from_before_the_lint_still_reads():
    """A phase begun on a plugin before AIWF-105 has entries without `lint`:
    the reviewer's line and the fix round's read them as they always did."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r = ScriptedLoop(slice_dir, [], repo_root=repo)
        target = run_loop.ResolvedTarget(
            "frontend", "project", Path(repo), component_argv("frontend"),
            Path(repo))
        entries = [{"project": "frontend", "outcome": "green",
                    "cmd": " ".join(component_argv("frontend"))},
                   {"project": "backend", "outcome": "nothing_ran",
                    "cmd": " ".join(component_argv("backend"))}]
        old = {"gate_green_commit": "deadbeefcafe0",
               "gate_green_log": "/g/gate_r1.log",
               "gate_cmd": entries[0]["cmd"], "gate_projects": entries}
        line = r._gate_line(old, "deadbeefcafe0", target)
        flat = line.replace("\n", " ")
        assert ("(deadbeefcafe): `kc project test --project frontend` in "
                f"{repo} — with full output in /g/gate_r1.log. It covers "
                "frontend: the phase's Target") in flat
        assert "The gate does not cover backend (defines no tests)" in flat
        assert "lint --project" not in line
        red = dict(old, gate_projects=[dict(e, outcome="red") for e in entries])
        assert r._red_cmds(red, target) == ("`kc project test --project "
                                            "frontend`, `kc project test "
                                            "--project backend`")
        # a `lint` off-shape makes the record none, as any torn entry does
        none = {k: v for k, v in old.items() if k != "gate_projects"}
        torn = dict(old, gate_projects=[dict(entries[0], lint={"cmd": 1}),
                                        entries[1]])
        assert r._gate_line(torn, "deadbeefcafe0", target) \
            == r._gate_line(none, "deadbeefcafe0", target)


# -- a spec-repo phase's gate: the plugin's spec check (AIWF-68) -------------
#
# AnsibleSpecs has no manifest, script or CI, so every phase there wrote a
# throwaway check of its own, and the driver's gate had nothing to run. A
# phase on the spec repo is gated by the plugin's spec_check.py over what it
# changed since the review's base, then by the repo's own `kc project test`
# where the phase's tree has a manifest.

def spec_gate_run(tmp, script, gate_rcs=(), manifest=False):
    """One phase on the spec repo, in its worktree, gated by the driver's
    own gate over scripted exit codes: (the slice, the worktree, the loop,
    the exit code)."""
    slice_dir, repo = make_slice(tmp)
    if manifest:
        gated_specs(tmp)
    specs_phase(slice_dir, tmp)
    r = KcExitLoop(slice_dir, script, repo_root=repo, gate_rcs=gate_rcs)
    code = run_to_exit(r)
    return slice_dir, specs_worktree(r), r, code


def spec_entry(work, outcome, base="base123"):
    return {"project": run_loop.SPEC_CHECK_NAME,
            "cmd": spec_check_cmd(work, base), "outcome": outcome}


def ran_spec_gate(loop):
    """A code-writer step's effect: it ran a spec-repo phase's gate through
    the wrapper — the check its spec says it opens with, against the merge
    base the wrapper resolves (the fake git's), then the repo's own command
    and its lint where there is one — and every command passed, or for the
    lint ran nothing."""
    spec = gate_spec(loop)
    check = (run_loop.spec_check_argv(loop.fake_git.merge_base,
                                      Path(spec["work_root"]))
             if spec["spec_check"] else None)
    ran_gate(*[(argv, 0) for argv in (check, spec["argv"]) if argv],
             *([(spec["lint_argv"], 3)] if spec["lint_argv"] else []))(loop)


def test_a_spec_repo_phase_is_gated_by_the_spec_check_against_its_base():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, work, r, code = spec_gate_run(
            tmp, [V["exec_done"], V["review_signoff"], *TAIL])
        assert code == 0 and not r.script
        check = run_loop.spec_check_argv("base123", work)
        assert check == ["python3", str(run_loop.TOOLS_DIR / "spec_check.py"),
                         "--base", "base123", str(work)]
        assert [(argv, cwd) for argv, cwd, _ in r.phase_gate_runs] \
            == [(check, work)]
        cmd = " ".join(check)
        ps = load_state(slice_dir)["phases"]["1"]
        assert ps["gate_cmd"] == cmd
        assert ps["gate_projects"] == [spec_entry(work, "green")]
        assert ps["gate_green_commit"] == r.fake_git.head
        assert Path(ps["gate_green_log"]).read_text() \
            == f"=== the spec check: `{cmd}` ===\n{cmd}: exit 0\n"
        prompt = reviewer_prompt(r)
        assert ("The deterministic test gate ran GREEN on this exact commit "
                f"({r.fake_git.head[:12]}): `{cmd}` in {work} — with full "
                f"output in {ps['gate_green_log']}. "
                + " ".join(run_loop.GATE_SPEC_CHECK_SENTENCE.split())
                + " The tests pass;") in prompt
        assert "It covers" not in prompt
        assert f"[P1] gate #1 running ({cmd})\n" \
            in (slice_dir / "log.txt").read_text()


def test_a_spec_repo_with_a_manifest_runs_its_own_gate_after_the_check():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, work, r, code = spec_gate_run(
            tmp, [V["exec_done"], V["review_signoff"], *TAIL], manifest=True)
        assert code == 0 and not r.script
        check = run_loop.spec_check_argv("base123", work)
        assert [(argv, cwd) for argv, cwd, _ in r.phase_gate_runs] \
            == [(check, work), (BARE_ARGV, work)]
        cmd = " ".join(check)
        ps = load_state(slice_dir)["phases"]["1"]
        assert ps["gate_cmd"] == "kc project test"
        # the repo's own lint beside its test (AIWF-105); the check none
        assert [(argv, cwd) for argv, cwd, _ in r.phase_lint_runs] \
            == [(BARE_LINT_ARGV, work)]
        assert ps["gate_projects"] == [
            spec_entry(work, "green"),
            {"project": "../specs", "cmd": "kc project test",
             "outcome": "green",
             "lint": {"cmd": "kc project lint", "outcome": "nothing_ran"}}]
        assert Path(ps["gate_green_log"]).read_text() == (
            f"=== the spec check: `{cmd}` ===\n{cmd}: exit 0\n"
            f"\n=== `kc project test` from {work} ===\n"
            "kc project test: exit 0\n"
            f"\n=== `kc project lint` from {work} ===\n"
            "kc project lint: exit 3\n")
        prompt = reviewer_prompt(r)
        assert (f"`{cmd}`, `kc project test` in {work} — with full output "
                "in") in prompt
        assert "It covers" not in prompt
        assert (f"[P1] gate #1 running ({cmd}, then kc project test, then "
                "kc project lint)\n") in (slice_dir / "log.txt").read_text()


def test_a_spec_gate_is_red_on_either_red_and_the_fix_round_names_it():
    def writers(loop):
        return [p for role, p in loop.prompts if role == "code-writer"]

    script = [V["exec_done"], V["exec_done"], V["review_signoff"], *TAIL]
    # the check red: a fix round, told what went red and how to re-gate
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, work, r, code = spec_gate_run(tmp, script, [1, 0])
        assert code == 0 and not r.script
        assert [h["outcome"] for h in gate_rows(slice_dir)] == ["red", "green"]
        assert load_state(slice_dir)["phases"]["1"]["gate_fix_rounds"] == 1
        fix = writers(r)[1]
        assert f"The gate went red on `{spec_check_cmd(work)}`;" in fix
        assert spec_check_hint(work) in fix
    # the check green, the repo's own red: red on that alone
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, work, r, code = spec_gate_run(tmp, script, [0, 1, 0, 0],
                                                 manifest=True)
        assert code == 0 and not r.script
        assert [h["outcome"] for h in gate_rows(slice_dir)] == ["red", "green"]
        assert "The gate went red on `kc project test`;" in writers(r)[1]
    # both red: both ran, and both are named
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, work, r, code = spec_gate_run(tmp, script, [1, 1, 0, 0],
                                                 manifest=True)
        assert code == 0
        assert len(r.phase_gate_runs) == 4
        assert (f"The gate went red on `{spec_check_cmd(work)}`, `kc project "
                "test`;") in writers(r)[1]
    # the repo's own ran nothing: green on the check, the repo unverified
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, work, r, code = spec_gate_run(
            tmp, [V["exec_done"], V["review_signoff"], *TAIL], [0, 3],
            manifest=True)
        assert code == 0 and not r.script
        ps = load_state(slice_dir)["phases"]["1"]
        assert [p["outcome"] for p in ps["gate_projects"]] \
            == ["green", "nothing_ran"]
        assert ps["gate_green_commit"] == r.fake_git.head
        assert ("The gate does not cover ../specs (defines no tests)"
                in reviewer_prompt(r))
    # the check's usage error is the driver's bug, never a red
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, work, r, code = spec_gate_run(tmp, [V["exec_done"]], [2])
        assert code == 3
        bail = json.loads((slice_dir / "bailout.json").read_text())
        assert bail["reason"] == "protocol_failure"
        assert f"`{spec_check_cmd(work)}` rejected its arguments" \
            in bail["details"]


def test_a_spec_check_red_is_never_asked_as_a_missing_service():
    """The spec repo's config may declare a service the pod does not run;
    a red of the check, which calls none, is a fix round all the same."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        (Path(tmp) / "specs" / ".kubecoder").mkdir()
        (Path(tmp) / "specs" / ".kubecoder" / "config.yaml").write_text(
            "services:\n  - use: postgres\n")
        specs_phase(slice_dir, tmp)
        r = KcExitLoop(slice_dir, [V["exec_done"], V["exec_done"],
                                   V["review_signoff"], *TAIL],
                       repo_root=repo, gate_rcs=[1, 0])
        with patched(run_loop, running_services=set):
            assert run_to_exit(r) == 0
        assert not (slice_dir / "bailout.json").exists()
        assert [h["outcome"] for h in gate_rows(slice_dir)] == ["red", "green"]


def test_a_spec_repo_phases_gate_spec_carries_its_check_for_the_wrapper():
    specs = []
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, work, r, code = spec_gate_run(tmp, [
            ("code-writer", DONE, lambda loop: specs.append(gate_spec(loop))),
            V["review_signoff"], *TAIL])
        assert code == 0
        # the check, not its command: the wrapper builds that over the
        # merge base it resolves from `base` (AIWF-104)
        assert specs == [{
            "phase": "1", "round": 1, "work_root": str(work),
            "gate_cwd": str(work), "base": "main", "spec_check": True,
            "argv": None, "fallback": None, "lint_argv": None,
            "lint_fallback": None, "touched": None}]
        assert run_loop.gate_spec_problem(specs[0]) is None
    specs.clear()
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, work, r, code = spec_gate_run(tmp, [
            ("code-writer", DONE, lambda loop: specs.append(gate_spec(loop))),
            V["review_signoff"], *TAIL], manifest=True)
        assert code == 0
        assert (specs[0]["spec_check"], specs[0]["argv"],
                specs[0]["lint_argv"]) == (True, BARE_ARGV, BARE_LINT_ARGV)


def test_the_writers_run_of_a_spec_gate_is_the_drivers_gate():
    for manifest in (False, True):
        with tempfile.TemporaryDirectory() as tmp, tree_is(TREE):
            slice_dir, work, r, code = spec_gate_run(tmp, [
                ("code-writer", DONE, ran_spec_gate), V["review_signoff"],
                *TAIL], manifest=manifest)
            assert code == 0 and not r.script
            assert r.phase_gate_runs == [], "the driver ran nothing itself"
            record = outputs_of(r) / "writer_gate_r1.json"
            assert [h.get("reused") for h in gate_rows(slice_dir)] \
                == [str(record)]
            ps = load_state(slice_dir)["phases"]["1"]
            assert ps["gate_projects"][0] == spec_entry(work, "green")
            assert len(ps["gate_projects"]) == (2 if manifest else 1)
            assert ps["gate_green_commit"] == r.fake_git.head


def test_a_writer_run_without_the_spec_check_is_not_the_drivers_gate():
    """A run of the repo's own gate alone — the wrapper of a plugin before
    the check, or `kc project test` by hand — is not the gate: the driver
    runs it, check first."""
    with tempfile.TemporaryDirectory() as tmp, tree_is(TREE):
        slice_dir, work, r, code = spec_gate_run(tmp, [
            wrote_gate((BARE_ARGV, 0)), V["review_signoff"], *TAIL],
            manifest=True)
        assert code == 0
        check = run_loop.spec_check_argv("base123", work)
        assert [argv for argv, _, _ in r.phase_gate_runs] == [check, BARE_ARGV]
        assert ("[P1] the writer's gate run (writer_gate_r1.json) not reused "
                "— it ran `kc project test`, the gate is "
                f"`{' '.join(check)}`, `kc project test`, `kc project lint`; "
                "running the gate") \
            in (slice_dir / "log.txt").read_text()
    # an older base in the check is another command
    with tempfile.TemporaryDirectory() as tmp, tree_is(TREE):
        def stale(loop):
            ran_gate((run_loop.spec_check_argv("0ld", specs_worktree(loop)),
                      0))(loop)

        slice_dir, work, r, code = spec_gate_run(tmp, [
            ("code-writer", DONE, stale), V["review_signoff"], *TAIL])
        assert code == 0
        assert [argv for argv, _, _ in r.phase_gate_runs] \
            == [run_loop.spec_check_argv("base123", work)]


def test_the_gate_wrapper_runs_a_spec_repos_check_first():
    with tempfile.TemporaryDirectory() as tmp, plain_git():
        repo, base = wrapper_repo(tmp)
        check = run_loop.spec_check_argv(base, repo)
        cmd = " ".join(check)
        # no manifest: the check is the gate, and its red is the gate's
        spec = write_spec(tmp, repo, None, spec_check=True)
        tee = FakeTee(rcs=[1])
        code, out, _ = run_wrapper(spec, tee)
        assert code == 1
        assert tee.calls == [(check, repo)]
        record = record_of(spec)
        assert run_loop.writer_gate_record_problem(record) is None
        assert ([c["argv"] for c in record["commands"]], record["outcome"]) \
            == ([check], "red")
        assert out.startswith(f"=== the spec check: `{cmd}` ===\n")
        assert out.rstrip("\n").endswith(f"=== gate RED: `{cmd}` ===")
        # a manifest: the check, then the repo's own
        spec = write_spec(tmp, repo, BARE_ARGV, spec_check=True)
        tee = FakeTee()
        code, out, _ = run_wrapper(spec, tee)
        assert code == 0
        assert tee.calls == [(check, repo), (BARE_ARGV, repo)]
        assert out.index(f"=== the spec check: `{cmd}` ===") \
            < out.index(f"{cmd}: exit 0") \
            < out.index(f"\n=== `kc project test` from {repo} ===") \
            < out.index("kc project test: exit 0")
        # a spec with no command at all, or a check flag that is none, is
        # no spec
        for argv, bad in ((None, False), (BARE_ARGV, "spec_check.py")):
            spec = write_spec(tmp, repo, argv, spec_check=bad)
            code, _, err = run_wrapper(spec, FakeTee())
            assert code == 2 and "is not a gate spec" in err, err


def test_the_gate_wrapper_resolves_the_merge_base_when_its_run_begins():
    """AIWF-104: the spec names the base branch, and the wrapper takes `git
    merge-base <base> HEAD` itself at every run — so a writer that rebases
    its branch onto a moved base, or merges the base into it, mid-round
    gates the phase's own range: the base's commits touch no component, and
    the spec check reads from the new merge base."""
    with tempfile.TemporaryDirectory() as tmp, plain_git():
        repo, fork = wrapper_repo(tmp)
        sh(repo, "checkout", "-qb", "phase/074-P1")
        (repo / "frontend" / "App.tsx").write_text("the phase's\n")
        sh(repo, "commit", "-qam", "P1")
        spec = write_spec(tmp, repo, component_argv("frontend"),
                          touched={"target": "frontend", "waived": []},
                          spec_check=True)

        def gated(base):
            return [(run_loop.spec_check_argv(base, repo), repo),
                    (component_argv("frontend"), repo)]

        def base_moves(path, text):
            sh(repo, "checkout", "-q", "main")
            (repo / path).write_text(text)
            sh(repo, "commit", "-qam", f"main: {path}")
            moved = sh(repo, "rev-parse", "HEAD")
            sh(repo, "checkout", "-q", "phase/074-P1")
            return moved

        tee = FakeTee()
        assert run_wrapper(spec, tee)[0] == 0
        assert tee.calls == gated(fork)
        # another session lands backend work on main; the writer rebases
        moved = base_moves("backend/api.py", "main's\n")
        sh(repo, "rebase", "-q", "main")
        tee = FakeTee()
        assert run_wrapper(spec, tee)[0] == 0
        assert tee.calls == gated(moved), "backend is main's, not the phase's"
        assert [c["argv"] for c in record_of(spec)["commands"]] \
            == [argv for argv, _ in gated(moved)]
        # merged rather than rebased: the merge base is main's tip all the same
        again = base_moves("backend/worker/job.py", "main's again\n")
        sh(repo, "merge", "-q", "--no-edit", "main")
        tee = FakeTee()
        assert run_wrapper(spec, tee)[0] == 0
        assert tee.calls == gated(again)


def test_a_gate_spec_names_its_base_branch_and_whether_it_checks_the_spec():
    problem = run_loop.gate_spec_problem
    good = {"phase": "1", "round": 1, "work_root": "/w", "gate_cwd": "/w",
            "base": "main", "spec_check": False,
            "argv": component_argv(PROJECT), "fallback": None,
            "touched": {"target": PROJECT, "waived": []}}
    assert problem(good) is None
    # a spec repo with no manifest: its spec check is the whole gate
    assert problem(dict(good, spec_check=True, argv=None)) is None
    assert problem(dict(good, argv=None)) == "`argv` is not a command"
    # the lint beside the test (AIWF-105); a spec from before it has none
    linted = dict(good, lint_argv=lint_argv(PROJECT), lint_fallback=None)
    assert problem(linted) is None
    assert problem(dict(linted, lint_argv="kc project lint")) \
        == "`lint_argv` is not a command"
    assert problem(dict(linted, lint_fallback=[])) \
        == "`lint_fallback` is not a command"
    assert problem({k: v for k, v in good.items() if k != "base"}) \
        == "no `base` of type str"
    assert problem(dict(good, base="")) == "`base` is empty"
    assert problem(dict(good, spec_check="yes")) \
        == "no `spec_check` of type bool"
    # the shape before AIWF-104 — a merge base baked in, the check's command
    # in place of the flag — is no spec the wrapper runs
    before = {k: v for k, v in good.items() if k not in ("base", "spec_check")}
    before.update(check=None, touched={"merge_base": "abc123",
                                       "target": PROJECT, "waived": []})
    assert problem(before) == "no `base` of type str"


def test_the_drivers_spec_gate_runs_the_real_check_on_the_phases_tree():
    """No scripted exit code: the driver's gate runs spec_check.py itself,
    in a real tree, and reads its exit code."""
    class RealCheckLoop(ScriptedLoop):
        _run_gate = RunLoop._run_gate

    with tempfile.TemporaryDirectory() as tmp, plain_git():
        slice_dir, repo = make_slice(tmp)
        work = Path(tmp) / "scratch" / "worktrees" / "specs" / "074-P1"
        work.mkdir(parents=True)
        (work / "README.md").write_text("# specs\n")
        sh(work, "init", "-q", "-b", "main")
        sh(work, "add", "-A")
        sh(work, "commit", "-qm", "base")
        base = sh(work, "rev-parse", "HEAD")
        r = RealCheckLoop(slice_dir, [], repo_root=repo)
        r.state = {"phases": {}, "history": []}
        specs = run_loop.spec_root_for(slice_dir)
        target = run_loop.ResolvedTarget(
            "../specs", "sibling", specs, None, specs,
            manifest_gate=True).in_worktree(work)
        ps = r._phase_state("1")
        outputs = outputs_of(r)
        outputs.mkdir(parents=True)
        (work / "page.md").write_text("| a | b |\n|---|---|\n| 1 |\n")
        green, log = r._run_gate("1", ps, outputs, target, base)
        assert not green
        assert "page.md:3: a table row with 1 cell, its header 2\n" \
            in log.read_text()
        assert ps["gate_projects"] == [spec_entry(work, "red", base)]
        assert ps["gate_green_commit"] is None
        (work / "page.md").write_text("| a | b |\n|---|---|\n| 1 | 2 |\n")
        green, log = r._run_gate("1", ps, outputs, target, base)
        assert green
        assert (f"spec_check: clean — 1 file changed since {base[:12]}\n"
                in log.read_text())
        assert [h["outcome"] for h in r.state["history"]] == ["red", "green"]


def test_a_spec_repo_phases_dispatch_names_the_spec_check_as_its_gate():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, work, r, code = spec_gate_run(
            tmp, [V["exec_done"], V["review_signoff"], *TAIL])
        assert code == 0
        writer = next(p for role, p in r.prompts if role == "code-writer")
        outputs = slice_dir / "phases" / "P1"
        assert ("Run the phase's test gate yourself before handing back — "
                f"through {wrapper_cmd(outputs)}, which runs the driver's own "
                f"gate: {spec_check_hint(work)}; and `kc project test` from "
                f"{work} after it, once this phase adds "
                f"`.kubecoder/project.yaml`. {run_loop.GATE_REUSE_HINT}.") \
            in writer
        assert "own conventions" not in writer
    # a sibling repo with no manifest keeps its own conventions
    with tempfile.TemporaryDirectory() as tmp:
        sib = make_sibling(tmp, manifest=False)
        slice_dir, repo = make_slice(tmp)
        (slice_dir / "plan.md").write_text(
            "# plan\n\n" + phase_section("1", "Chart", "../Sibling"))
        r = ScriptedLoop(slice_dir, [V["exec_done"], V["review_signoff"],
                                     *TAIL], repo_root=repo)
        assert run_to_exit(r) == 0
        writer = next(p for role, p in r.prompts if role == "code-writer")
        assert (f"handing back ({sib.resolve()} has no kc manifest — gate per "
                "that repo's own conventions; if this phase adds "
                "`.kubecoder/project.yaml`, the driver's gate is `kc project "
                f"test` from {sib.resolve()}).") in writer
        assert "spec check" not in writer


def test_a_dry_run_names_the_spec_check_as_a_spec_repo_phases_gate():
    check = (f"python3 {run_loop.TOOLS_DIR / 'spec_check.py'} --base <the "
             "phase's base> <its worktree>")
    for manifest, gate in ((False, check),
                           (True, f"{check}, then kc project test")):
        with tempfile.TemporaryDirectory() as tmp:
            slice_dir, repo = make_slice(tmp)
            if manifest:
                gated_specs(tmp)
            specs = specs_phase(slice_dir, tmp)
            loop = RunLoop(slice_dir, resume=False)
            loop._spec_root = specs
            rc_, out, err = dry_run_from(loop, repo)
            assert rc_ == 0, err
            assert f"target=../specs [sibling]  root={specs}  gate: {gate}\n" \
                in out


# -- kc's full output inlined into the gate log (AIWF-85) ---------------------
#
# `kc project test` prints a status line and the last few lines per
# statement, and closes on `full output: /tmp/kc/project/test-….log` — a file
# kc keeps for 20 runs and a restart loses. The reviewer, told the gate log
# holds the full output, had to open /tmp; the driver now appends that file.

class KcFullOutputLoop(KcExitLoop):
    """KcExitLoop whose phase-gate kc runs close the way kc's do, on a
    `full output:` line — naming `full_outputs` in order, one per run, and
    none once spent."""

    def __init__(self, slice_dir, script, full_outputs=(), **kw):
        super().__init__(slice_dir, script, **kw)
        self.full_outputs = list(full_outputs)

    def _gate_exec(self, argv, cwd, log_file):
        rc_ = super()._gate_exec(argv, cwd, log_file)
        if not self._sweeping and self.full_outputs:
            log_file.write(f"full output: {self.full_outputs.pop(0)}\n")
        return rc_


def kc_full_log(tmp, name, text):
    path = Path(tmp) / name
    path.write_text(text)
    return str(path)


def test_the_gate_log_inlines_kcs_full_output_after_kcs_own_lines():
    """The history row's summary stays kc's own last line, never the
    inlined file's."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        full = kc_full_log(tmp, "test-20261021T010554Z-653.log",
                           "collected 12 items\nlast line of the full log\n")
        r = KcFullOutputLoop(slice_dir, [V["exec_done"], V["review_signoff"],
                                         *TAIL],
                             repo_root=repo, gate_rcs=[0],
                             full_outputs=[full])
        assert run_to_exit(r) == 0
        state = load_state(slice_dir)
        log = Path(state["phases"]["1"]["gate_green_log"]).read_text()
        lint = " ".join(lint_argv(PROJECT))
        assert log == (f"kc project test --project {PROJECT}: exit 0\n"
                       f"full output: {full}\n"
                       f"\n=== kc's full output ({full}) ===\n"
                       "collected 12 items\nlast line of the full log\n"
                       f"\n=== `{lint}` from {repo} ===\n{lint}: exit 3\n")
        row = next(h for h in state["history"] if h["role"] == "gate")
        assert row["summary"] == f"full output: {full}"


def test_a_full_output_file_that_is_gone_is_said_and_not_inlined():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        gone = str(Path(tmp) / "test-rotated-out.log")
        r = KcFullOutputLoop(slice_dir, [V["exec_done"], V["review_signoff"],
                                         *TAIL],
                             repo_root=repo, gate_rcs=[0],
                             full_outputs=[gone])
        assert run_to_exit(r) == 0
        state = load_state(slice_dir)
        log = Path(state["phases"]["1"]["gate_green_log"]).read_text()
        assert (f"full output: {gone}\n\n=== kc's full output ({gone}) is "
                "gone — not inlined ===\n\n=== `kc project lint") in log
        row = next(h for h in state["history"] if h["role"] == "gate")
        assert row["summary"] == f"full output: {gone}"


def test_the_missing_tool_scan_never_reads_the_inlined_full_output():
    """A red whose kc lines are clean is a fix round, even when a failing
    test's full output quotes cexec's missing-tool line."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        full = kc_full_log(tmp, "test-red.log",
                           f"FAILED test_cexec_message\n{CEXEC_MISSING}")
        r = KcFullOutputLoop(slice_dir, [V["exec_done"], V["exec_done"],
                                         V["review_signoff"], *TAIL],
                             repo_root=repo, gate_rcs=[1, 0],
                             full_outputs=[full, full])
        assert run_to_exit(r) == 0
        assert not r.script
        assert not (slice_dir / "bailout.json").exists()
        ps = load_state(slice_dir)["phases"]["1"]
        assert ps["gate_fix_rounds"] == 1
        red_log = Path(ps["gate_green_log"]).with_name("gate_r1.log")
        assert f"=== kc's full output ({full}) ===\n" \
            f"FAILED test_cexec_message\n{CEXEC_MISSING}" in red_log.read_text()


def test_each_root_gate_step_inlines_its_own_full_output():
    """Step 2's pointer search starts where step 2 began: step 1's pointer
    and its inlined file are never inlined again."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp, phases=[("1", "First phase",
                                                   "root")])
        root_full = kc_full_log(tmp, "test-root.log", "ROOT-FULL\n")
        bare_full = kc_full_log(tmp, "test-bare.log", "BARE-FULL\n")
        r = KcFullOutputLoop(slice_dir, [V["exec_done"], V["review_signoff"],
                                         *TAIL],
                             repo_root=repo, gate_rcs=[3, 0],
                             full_outputs=[root_full, bare_full])
        with patched(run_loop, load_project_dirs=root_components):
            assert run_to_exit(r) == 0
        assert [argv for argv, _, _ in r.phase_gate_runs] == [ROOT_ARGV,
                                                               BARE_ARGV]
        state = load_state(slice_dir)
        log = Path(state["phases"]["1"]["gate_green_log"]).read_text()
        marks = [log.index(s) for s in (
            "--project root: exit 3", f"full output: {root_full}",
            f"=== kc's full output ({root_full}) ===", "ROOT-FULL",
            "ran nothing (exit 3) — the gate is the whole repo",
            "kc project test: exit 0", f"full output: {bare_full}",
            f"=== kc's full output ({bare_full}) ===", "BARE-FULL")]
        assert marks == sorted(marks)
        assert log.count("=== kc's full output") == 2
        row = next(h for h in state["history"] if h["role"] == "gate")
        assert row["summary"] == f"full output: {bare_full}"
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp, phases=[("1", "First phase",
                                                   "root")])
        root_full = kc_full_log(tmp, "test-root.log", "ROOT-FULL\n")
        r = KcFullOutputLoop(slice_dir, [V["exec_done"], V["review_signoff"],
                                         *TAIL],
                             repo_root=repo, gate_rcs=[3, 0],
                             full_outputs=[root_full])
        with patched(run_loop, load_project_dirs=root_components):
            assert run_to_exit(r) == 0
        log = Path(load_state(slice_dir)["phases"]["1"]["gate_green_log"]
                   ).read_text()
        assert log.count("=== kc's full output") == 1
        assert log.count("ROOT-FULL") == 1
        assert log.index("ROOT-FULL") < log.index("kc project test: exit 0") \
            < log.index("=== `kc project lint --project root`")


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
        report = entries_in_full(slice_dir)
        assert ("### E1 — P1 merged with unresolved review findings after r2"
                in report)
        assert "advisory only" in report
        assert "F1 [Major/blocking]: wrong branch on empty input" in report
        assert "F2 [Minor/advisory]: stale comment" in report
        assert "code_review_r2.md" in report
        assert "**Provenance:** witnessed — consult 1 (review-funding, P1 r2)" in report
        # The driver's stock consequence for a merge: the findings stand.
        assert ("**Consequence:** the findings listed above are in the merged "
                "tree as the reviewer left them") in report
        assert "**Disposition:**" not in report
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
        assert "### E" not in load_report(slice_dir)


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
        report = entries_in_full(slice_dir)
        assert "### E1 — Fix round after review r1 of P1 refuted F1" in report
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
close_out = sys.modules[run_loop.ReportError.__module__]

def test_run_start_creates_and_commits_the_report_once():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r = ScriptedLoop(slice_dir, [V["exec_done"], V["review_signoff"],
                                     *TAIL], repo_root=repo)
        assert run_to_exit(r) == 0
        record = (slice_dir / "close-out-record.md").read_text()
        assert record.startswith("# Close-out record — slice 074 test slice\n")
        specs = r.fake_git.specs_ops()
        creates = [c for c in specs if c[2] == "commit"
                   and c[4] == "slice 074: close-out report"]
        assert len(creates) == 1
        # A run started with the plan loop's report in place leaves it be.
        (slice_dir / "state.json").unlink()
        run_loop.append_entry(slice_dir, "event", "planning saw something",
                              "body", consequence="none")
        plan = (slice_dir / "plan.md").read_text()
        (slice_dir / "plan.md").write_text(re.sub(r" ✅ DONE \S+", "", plan))
        r2 = ScriptedLoop(slice_dir, [V["exec_done"], V["review_signoff"],
                                      *TAIL], repo_root=repo)
        assert run_to_exit(r2) == 0
        assert "### E1 — planning saw something" in load_report(slice_dir)
        assert not [c for c in r2.fake_git.specs_ops()
                    if c[2] == "commit" and c[4] == "slice 074: close-out report"]


def test_resume_creates_the_report_when_the_run_predates_it():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        (slice_dir / "state.json").write_text(
            json.dumps(resume_state(PROJECT, stage="executor")))
        r = ScriptedLoop(slice_dir, [V["exec_done"], V["review_signoff"],
                                     *TAIL], resume=True, repo_root=repo)
        r.fake_git.branches.add("phase/074-P1")
        assert run_to_exit(r) == 0
        assert (slice_dir / "close-out.json").exists()
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
        # …and the tool, in the one dispatch line — the installed
        # close_out.py by absolute path, in the invocation and in the
        # pointer to its labels, the ban on hand edits, and `append`'s
        # arguments — never restated within a prompt.
        report = slice_dir / "close-out.md"
        for _, prompt in r.prompts:
            assert prompt.count(CLOSE_OUT_TOOL) == 2, prompt
            assert f"`python3 {CLOSE_OUT_TOOL}\n<verb> {report} …`" in prompt
            assert f"`python3 {CLOSE_OUT_TOOL} labels` prints" in prompt
            assert "never edit either file by hand" in prompt
            assert prompt.count("close_out.py append <close-out.md> --kind") == 1
        # and no prompt still speaks of cards — but for the ruling words
        # `append`'s --proposal names
        append = close_out.verb_usage("append")
        assert not any("card" in p.replace(append, "") for _, p in r.prompts)


def test_report_is_rendered_before_the_doc_phase_and_at_completion():
    """A run that stalls in the doc phase leaves a report that can be read,
    so the driver renders before dispatching the doc-writer: the asks by
    route, graded entries first, struck entries' headings in the record's
    Record. The wrap-up the unlabelled entries wait for renders once more
    when it is over, and completion renders again (idempotent) and then
    stamps."""
    plant = {}

    def plant_entries(loop):
        # The test phase's session leaves entries in arrival order, one of
        # them struck — no write renders.
        d = loop.slice_dir
        run_loop.append_entry(d, "Bugs", "a nit", "b1", consequence="c1",
                              provenance="read P1 r1", severity="nit")
        run_loop.append_entry(d, "Bugs", "the major one", "b2",
                              consequence="c2", provenance="witnessed P2",
                              severity="major")
        run_loop.append_entry(d, "Bugs", "a minor", "b3", consequence="c3",
                              provenance="read P1 r1", severity="minor")
        close_out.strike_entry(d, "B1", "dup of B3")
        plant["planted"] = load_report(d)

    def snapshot(loop):
        plant["at_doc_dispatch"] = (
            loop.slice_dir / "close-out-record.md").read_text()

    script = [
        V["exec_done"], V["review_signoff"], V["consult_complete"],
        ("test-agent", {"outcome": "clean", "summary": "ok"}, plant_entries),
        ("doc-writer", {"outcome": "done", "summary": "docs"}, snapshot),
    ]
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r = ScriptedLoop(slice_dir, script, repo_root=repo)
        assert run_to_exit(r) == 0
        assert plant["planted"] == "", "no write renders"
        seen = plant["at_doc_dispatch"]
        # Rendered when the doc-writer was dispatched: the unlabelled
        # defects asked, major before minor; the struck nit's heading in the
        # Record, its body in the store.
        body = seen[seen.index("\n## "):]
        assert (body.index("## Asked")
                < body.index("### B2 — the major one · major")
                < body.index("### B3 — a minor · minor")
                < body.index("## Record")
                < body.index("### ~~B1 — a nit · nit~~ — dup of B3"))
        assert "b1\n" not in body
        doc = (slice_dir / "close-out.md").read_text()
        assert doc.index("## the major one") < doc.index("## a minor")
        # Completion rendered again and stamped: byte-identical sections,
        # header stamped, counts unchanged.
        final = (slice_dir / "close-out-record.md").read_text()
        assert final[final.index("\n## "):] == body
        assert "<not yet stamped>" not in final
        log = (slice_dir / "log.txt").read_text()
        assert ("close-out report: to you 0 · card requests 0 · wrap-up 0 · "
                "unlabelled 2 · closed 0 · record 0 — A 0 · D 0 · E 0 · B 2 · "
                "P 0 · T 0 · I 0") in log
        assert log.count("close-out rendered: ") == 3
        assert ("close-out rendered: close-out-record.md and close-out.md written: "
                "2 asks") in log
        assert len(r.wrap_up_sessions) == 1


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
        header = report[report.index("Run:"):report.index("\n## ")]
        header = " ".join(header.split())
        assert "2 phases (1 planned, P2 appended)" in header
        assert "1 bail-out" in header
        assert "1 test round" in header
        assert "doc phase done" in header
        assert "$" not in header      # no cost block yet — omitted, not guessed
        log = (slice_dir / "log.txt").read_text()
        # the one event is that bail, written by the resume, in the record
        assert ("close-out report: to you 0 · card requests 0 · wrap-up 0 · "
                "unlabelled 0 · closed 0 · record 1 — A 0 · D 0 · E 1 · B 0") in log


def test_a_bail_renders_the_report_and_commits_nothing():
    """A run that stops leaves its report rendered from the store as it
    stood — the header naming the stage it stopped in — and the files as
    they are: a bail adds no commit."""
    def appends(loop):
        run_loop.append_entry(loop.slice_dir, "defect", "found on the way", "b",
                              consequence="c")

    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r = ScriptedLoop(slice_dir, [("code-writer", {"outcome": "blocked",
                                                       "summary": "no creds"},
                                      appends)],
                         repo_root=repo)
        assert run_to_exit(r) == 3
        report = load_report(slice_dir)
        assert "### B1 — found on the way" in report
        assert "run bailed in phases" in " ".join(report.split())
        assert ("close-out rendered: close-out-record.md and close-out.md written: 1 ask"
                in (slice_dir / "log.txt").read_text())
        commits = [c for c in r.fake_git.specs_ops() if c[2] == "commit"]
        assert [c[4] for c in commits] == ["slice 074: close-out report"]

    # A render that fails is logged; the bail keeps its code.
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)

        def breaks_the_store(loop):
            (loop.slice_dir / "close-out.json").write_text("{ torn")

        r = ScriptedLoop(slice_dir, [("code-writer", {"outcome": "question",
                                                       "summary": "which?"},
                                      breaks_the_store)],
                         repo_root=repo)
        assert run_to_exit(r) == 4
        assert "close-out not rendered: " in (slice_dir / "log.txt").read_text()


def entries_in_full(slice_dir):
    """Every entry of the report, struck ones too, in full as `close_out.py
    show` prints it: the rendered report carries the ask alone, so what the
    driver wrote under an entry — body, notes, Provenance — is read from
    the store. Empty before the store holds an entry."""
    try:
        data = json.loads((slice_dir / "close-out.json").read_text())
    except FileNotFoundError:
        return ""
    ids = [e["id"] for e in data["entries"]]
    return close_out.show_view(slice_dir, ids) if ids else ""


def test_every_stop_becomes_one_notable_event_written_by_the_resume():
    """The report's Events said the run recorded no bail-out beneath a
    header counting one. Each stop is written once its resume has the report
    and the spec tree back — once, however many resumes follow."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r1 = ScriptedLoop(slice_dir, [("code-writer", {
            "outcome": "blocked", "summary": "no creds for the registry"})],
            repo_root=repo)
        assert run_to_exit(r1) == 3
        row, = load_state(slice_dir)["bailouts"]
        assert row["details"] == "no creds for the registry"
        assert row["run_phase"] == "phases" and "reported" not in row
        assert "### E" not in entries_in_full(slice_dir), "not while stopped"

        r2 = ScriptedLoop(slice_dir, [("code-writer", {
            "outcome": "question", "summary": "which registry, prod or dev?"})],
            resume=True, repo_root=repo)
        assert run_to_exit(r2) == 4
        events = entries_in_full(slice_dir)
        assert "### E1 — Run stopped (blocked) in P1\n" in events
        assert "> no creds for the registry" in events
        assert "resumed" in events
        assert ("**Provenance:** witnessed — the driver's bail record in "
                "state.json") in events
        assert "**Consequence:** none the loop acts on" in events
        assert "### E2" not in events, "the question is still open"
        first, second = load_state(slice_dir)["bailouts"]
        assert first["reported"] is True and "reported" not in second

        r3 = ScriptedLoop(slice_dir, [V["exec_done"], V["review_signoff"],
                                      *TAIL], resume=True, repo_root=repo)
        assert run_to_exit(r3) == 0
        events = entries_in_full(slice_dir)
        assert events.count("Run stopped (blocked) in P1") == 1
        assert "### E2 — Run paused for an operator question in P1\n" \
            in events
        assert "> which registry, prod or dev?" in events
        assert "### E3" not in events
        assert all(b["reported"] for b in load_state(slice_dir)["bailouts"])


def test_a_resume_that_dispatches_nothing_reports_the_stop_at_completion():
    """A stop in the doc stage of a project that runs no doc phase, with
    nothing waiting for the wrap-up: the resume completes without a single
    dispatch, and the stop is still entered — once the run is over."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(
            tmp, phases=[("1", "First", PROJECT, True)],
            config=rc(doc=False))
        state = merged_state(repo, "docs")
        state["bailouts"] = [
            {"reason": "blocked", "phase": None, "question": False,
             "ts": "2026-09-21T08:00:00.000000+02:00", "run_phase": "docs",
             "details": "the cluster was down"}]
        (slice_dir / "state.json").write_text(json.dumps(state))
        r = ScriptedLoop(slice_dir, [], resume=True, repo_root=repo)
        assert run_to_exit(r) == 0
        assert not r.spawned and not r.wrap_up_sessions
        assert "### E1 — Run stopped (blocked)" in entries_in_full(slice_dir)
        assert load_state(slice_dir)["bailouts"][0]["reported"] is True


def test_a_stop_outside_a_phase_and_a_row_without_details_are_reported():
    """No phase named: the stage the run stopped in heads the entry. A row an
    earlier driver wrote has no details, and says where they are."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(
            tmp, phases=[("1", "First", PROJECT, True)])
        state = merged_state(repo, "test")
        state["bailouts"] = [
            {"reason": "unpushed", "phase": None, "question": False,
             "ts": "2026-09-20T10:11:12.000000+02:00"},
            {"reason": "blocked", "phase": None, "question": False,
             "ts": "2026-09-21T08:00:00.000000+02:00", "run_phase": "test",
             "details": "the cluster was down\n\n### not a heading"}]
        (slice_dir / "state.json").write_text(json.dumps(state))
        r = ScriptedLoop(slice_dir, [V["test_clean"], V["doc_done"]],
                         resume=True, repo_root=repo)
        assert run_to_exit(r) == 0
        events = entries_in_full(slice_dir)
        assert "### E1 — Run stopped (unpushed) outside any phase" in events
        assert "the stop is in full in log.txt" in events
        assert "Stopped 2026-09-20 10:11; resumed" in events
        assert "### E2 — Run stopped (blocked) in the test phase" in events
        # quoted, so an agent's text can never open an entry of its own
        assert "> ### not a heading" in events and "### E3" not in events


# AIWF-87: the driver's own entries were left in the store to ride the
# report's next commit — a role's, which stages the store by name and so
# carried them too (a P9 code-reviewer's commit held the loop's E1). The
# driver commits the store before every dispatch that finds it changed. The
# fake sees only the spec repo's pathspec commits, so a test marks the store
# committed where a real run's commits would have left it so.

def store_committed(loop):
    """The store as it stands is the one the spec repo's last commit holds."""
    store = run_loop.store_path(loop.slice_dir)
    loop.fake_git.specs_committed[str(store)] = store.read_text()


def committed_entry_ids(loop):
    """The ids of the entries the spec repo's last commit of the store
    holds — none before one."""
    text = loop.fake_git.specs_committed.get(
        str(run_loop.store_path(loop.slice_dir)))
    return [e["id"] for e in json.loads(text)["entries"]] if text else []


def stopped_in_p1(slice_dir):
    """The planned report in place, and a run that stopped in P1's executor
    with the stop not entered yet — its resume enters it at the first
    dispatch."""
    run_loop.init_report(slice_dir)
    state = resume_state(PROJECT, stage="executor")
    state["bailouts"] = [
        {"reason": "blocked", "phase": "1", "question": False,
         "ts": "2026-10-20T08:00:00.000000+02:00", "run_phase": "phases",
         "details": "no creds for the registry"}]
    (slice_dir / "state.json").write_text(json.dumps(state))


BEFORE_P1_WRITER = "slice 074: close-out report before P1 code-writer"


def test_the_drivers_entries_are_committed_before_the_next_dispatch():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        stopped_in_p1(slice_dir)
        seen = {}

        def appends_and_commits(loop):
            g, store = loop.fake_git, run_loop.store_path(loop.slice_dir)
            seen["spawned"] = (list(g.specs_commits),
                               g.specs_committed.get(str(store))
                               == store.read_text(),
                               committed_entry_ids(loop))
            # the role's own entry, the store committed by name
            close_out.append_entry(loop.slice_dir, "defect", "the writer's",
                                   "body", consequence="c")
            loop.specs_git("add", "--", str(store))
            loop.specs_git("commit", "-m", "slice 074: P1 built", "--",
                           str(store))
            seen["role"] = committed_entry_ids(loop)

        def reviews(loop):
            seen["review"] = list(loop.fake_git.specs_commits)

        script = [("code-writer", {"outcome": "done", "summary": "built"},
                   appends_and_commits),
                  ("code-reviewer", {"outcome": "signoff", "summary": "ok"},
                   reviews),
                  *TAIL]
        r = SpawningLoop(slice_dir, script, resume=True, repo_root=repo)
        r.fake_git.branches.add("phase/074-P1")
        store_committed(r)
        with patched(run_loop, run_kc_session=r.run_kc_session):
            assert run_to_exit(r) == 0
        # the resume's stop entry, committed on its own before the writer ran
        assert seen["spawned"] == ([BEFORE_P1_WRITER], True, ["E1"])
        # so the writer's commit of the store adds its own entry, nothing else
        assert seen["role"] == ["E1", "B1"]
        # the store it committed is no reason for another commit
        assert seen["review"] == [BEFORE_P1_WRITER, "slice 074: P1 built"]
        assert (f"[close-out] committed close-out.md: {BEFORE_P1_WRITER}"
                in (slice_dir / "log.txt").read_text())


def test_a_render_changed_alone_is_not_committed_before_a_dispatch():
    """A dispatch that finds the store unchanged commits nothing."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        run_loop.init_report(slice_dir)
        seen = []

        def looks(loop):
            seen.append((list(loop.fake_git.specs_commits),
                         loop.report_path.exists()))

        r = SpawningLoop(slice_dir, [("code-writer", {
            "outcome": "blocked", "summary": "no creds"}, looks)],
            repo_root=repo)
        store_committed(r)
        with patched(run_loop, run_kc_session=r.run_kc_session):
            assert run_to_exit(r) == 3
        assert seen == [([], False)]


def test_a_report_commit_that_fails_before_a_dispatch_is_logged_not_fatal():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        stopped_in_p1(slice_dir)
        seen = []
        r = SpawningLoop(slice_dir, [
            ("code-writer", {"outcome": "done", "summary": "built"},
             lambda loop: seen.append(list(loop.fake_git.specs_commits))),
            V["review_signoff"], *TAIL], resume=True, repo_root=repo)
        r.fake_git.branches.add("phase/074-P1")
        store_committed(r)
        r.fake_git.fails.add((
            "-C", str(r.slice_dir), "commit", "-m", BEFORE_P1_WRITER, "--",
            str(run_loop.store_path(r.slice_dir))))
        with patched(run_loop, run_kc_session=r.run_kc_session):
            assert run_to_exit(r) == 0
        # the writer ran all the same, with the stop entry uncommitted
        assert r.sessions[0][0] == "code-writer" and seen == [[]]
        log = (slice_dir / "log.txt").read_text()
        assert (f"[close-out] report not committed before P1 code-writer "
                f"(git -C {r.slice_dir} commit -m {BEFORE_P1_WRITER} --"
                in log)
        assert "failed) — the driver's entries ride its commit" in log
        # the next dispatch commits what that one could not
        assert r.fake_git.specs_commits[0] == \
            "slice 074: close-out report before P1 code-reviewer"

    # Any error, not a Bailout alone, is logged the same way.
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        run_loop.init_report(slice_dir)
        r = ScriptedLoop(slice_dir, [], repo_root=repo)

        def breaks(message, label="[wrap-up]"):
            raise OSError("disk full")

        r._commit_report = breaks
        r._commit_own_entries("the test-agent nudge")
        assert ("[close-out] report not committed before the test-agent "
                "nudge (OSError: disk full)"
                in (slice_dir / "log.txt").read_text())


def test_a_nudge_commits_the_drivers_entries_before_it_resumes_the_session():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo, sib = sibling_phase_slice(tmp)
        ids = []

        def tests_then_the_driver_writes(loop):
            store_committed(loop)   # the test agent committed the store
            # an entry the driver writes after the round, before the nudge
            ids.append(loop._report("Notable events", "a driver event",
                                    "body", consequence="none"))

        r = ScriptedLoop(slice_dir, [
            V["exec_done"], V["review_signoff"], V["consult_complete"],
            (*V["test_clean"], tests_then_the_driver_writes), V["doc_done"]],
            repo_root=repo)
        r.fake_git.unpushed[str(sib)] = "1"
        seen = []

        def resumed(prompt, cwd, timeout, agent=None, resume_session=None,
                    **kw):
            g, store = r.fake_git, run_loop.store_path(r.slice_dir)
            seen.append((resume_session, list(g.specs_commits),
                         g.specs_committed.get(str(store))
                         == store.read_text()))
            g.unpushed.clear()   # the nudged session pushes
            result = run_loop.SessionResult()
            result.session_id = resume_session
            result.result_text = "pushed"
            return 0, result

        with patched(run_loop, run_kc_session=resumed):
            assert run_to_exit(r) == 0
        assert seen == [("sess-test", ["slice 074: close-out report before "
                                       "the test-agent nudge"], True)]
        assert ids[0] in committed_entry_ids(r)


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
            "bases": {}, "known_phases": [],
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
            return r._plan_targets(phases)[1]

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


def adds_manifest(repo):
    """A script step's effect: the session wrote `repo`'s kc manifest."""
    def effect(loop):
        (Path(repo) / run_loop.MANIFEST_REL).parent.mkdir(exist_ok=True)
        (Path(repo) / run_loop.MANIFEST_REL).write_text("projects: []\n")
    return effect


def test_a_sibling_phase_that_adds_its_manifest_is_gated_by_it():
    """The gate is read at gate time, in the phase's tree: the phase that
    bootstraps a sibling's `.kubecoder/project.yaml` runs `kc project test`
    there, though its Target resolved before the manifest existed — and its
    writer is told so up front (AIWF-77)."""
    with tempfile.TemporaryDirectory() as tmp:
        sib = make_sibling(tmp, manifest=False).resolve()
        slice_dir, repo = make_slice(tmp)
        writer = ("code-writer", {"outcome": "done", "summary": "built"},
                  adds_manifest(sib))
        r = ScriptedLoop(slice_dir, [writer, V["review_signoff"], *TAIL],
                         repo_root=repo)
        (slice_dir / "plan.md").write_text(
            "# plan\n\n" + phase_section("1", "Bootstrap", "../Sibling"))
        assert run_to_exit(r) == 0
        assert r.gate_calls == [("1", True)]
        assert r.gate_cwds == [sib]
        prompt = next(p for role, p in r.prompts if role == "code-writer")
        assert (f"({sib} has no kc manifest — gate per that repo's own "
                "conventions; if this phase adds `.kubecoder/project.yaml`, "
                f"the driver's gate is `kc project test` from {sib})"
                ) in prompt.replace("\n", " ")
        prompt = next(p for role, p in r.prompts if role == "code-reviewer")
        assert f"`kc project test` in {sib} — with full output" in prompt
        assert "ran GREEN on this exact commit" in prompt
        assert run_loop.GATE_UNVERIFIED_LINE not in prompt


def test_target_roots_are_the_pending_phases_repos_as_the_last_load_resolved():
    """state.json's `target_roots` is what the close-out routes read for a
    repo a phase still in its rounds targets: every pending phase's resolved
    root — started or not — replaced at every plan load, so a phase that is
    done drops out (its `landed` root stands for it)."""
    with tempfile.TemporaryDirectory() as tmp:
        sib = make_sibling(tmp)
        slice_dir, repo = make_slice(tmp, phases=[
            ("1", "App change", PROJECT),
            ("2", "Chart change", "../Sibling"),
        ])
        both = sorted([str(repo), str(sib.resolve())])
        r = ScriptedLoop(slice_dir, [("code-writer", {"outcome": "blocked",
                                                       "summary": "no creds"})],
                         repo_root=repo)
        assert run_to_exit(r) == 3
        # bailed in P1's rounds: P1's repo and P2's, which has not begun
        state = load_state(slice_dir)
        assert state["phases"]["1"]["landed"] is None
        assert "2" not in state["phases"]
        assert state["target_roots"] == both
        seen = []
        script = [
            V["exec_done"], V["review_signoff"],
            ("code-writer", {"outcome": "done", "summary": "built"},
             lambda loop: seen.append(list(loop.state["target_roots"]))),
            V["review_signoff"], *TAIL,
        ]
        r2 = ScriptedLoop(slice_dir, script, resume=True, repo_root=repo)
        assert run_to_exit(r2) == 0
        assert not r2.script
        # in P2's rounds P1 is done: its repo is gone from the list, not kept
        assert seen == [[str(sib.resolve())]]
        state = load_state(slice_dir)
        assert state["phases"]["1"]["landed"]["root"] == str(repo)
        assert state["target_roots"] == []


# -- a Target declared but not cloned (AIWF-73) --------------------------------
#
# A repo added to `.kubecoder/config.yaml` while the environment runs is
# cloned at the next pod start. Until then its sibling path is missing, and
# the loop took it for a wrong path: it nudged a session to fix a plan that
# was fine, then asked the operator.

def declaring(*dirs):
    """`declared_repo_dirs` answering as kc would with `dirs` in
    config.yaml, each at a GitHub url named after it."""
    return patched(run_loop, declared_repo_dirs=lambda: {
        Path(d).resolve(): f"https://github.com/acme/{Path(d).name}"
        for d in dirs})


def kc_never_asked():
    raise AssertionError("kc must not be asked for this Target")


def test_declared_repo_dirs_maps_every_declared_checkout_to_its_url():
    answer = subprocess.CompletedProcess([], 0, stdout=json.dumps({
        "repos": [
            {"url": "u1", "dir": "/work/App", "shared": False, "ref": None},
            {"url": "u2", "dir": "/work/AppSpecs", "shared": True},
            {"dir": "/work/NoUrl"},
            {"url": "u4", "dir": ""},
            {"url": "u5"},
            "not a repo"]}), stderr="")
    with patched(run_loop.subprocess, run=lambda *a, **kw: answer):
        assert REAL_DECLARED_REPO_DIRS() == {
            Path("/work/App").resolve(): "u1",
            Path("/work/AppSpecs").resolve(): "u2",
            Path("/work/NoUrl").resolve(): ""}
    broken = subprocess.CompletedProcess([], 1, stdout="", stderr="no pod")
    with patched(run_loop.subprocess, run=lambda *a, **kw: broken):
        try:
            REAL_DECLARED_REPO_DIRS()
        except ValueError as e:
            assert "kc env describe --output=json" in str(e)
        else:
            raise AssertionError("kc failing must be a ValueError")


def test_a_pending_phase_on_a_declared_uncloned_repo_stops_the_run_unnudged():
    """No plan error and no nudge — not even beside a real plan error: the
    run bails `target_not_cloned`, an error (exit 3) naming the fix. A
    directory that is there but no checkout reads the same."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp, phases=[
            ("1", "Rotate the secrets", "../SecretRotator"),
            ("2", "Chart it", "../Charts"),
            ("3", "A wrong name", "nosuch")])
        rotator, charts = Path(tmp) / "SecretRotator", Path(tmp) / "Charts"
        charts.mkdir()   # kc's mount point, nothing cloned into it
        r = ScriptedLoop(slice_dir, [], repo_root=repo)
        r._last_session = lambda: ("sess-earlier", "code-writer")
        nudges = []
        r._nudge = lambda *a, **kw: nudges.append(a)
        with declaring(rotator, charts):
            try:
                r._load_plan()
            except Bailout as e:
                bail = e
            else:
                raise AssertionError("an uncloned Target must stop the run")
        assert bail.reason == "target_not_cloned" and bail.question is False
        assert not nudges
        lines = bail.details.splitlines()
        assert "the plan is fine" in lines[0]
        assert len(lines) == 3, "one line per uncloned phase, no plan error"
        assert lines[1] == (
            "- phase P1: Target `../SecretRotator` is declared but not "
            "cloned: `.kubecoder/config.yaml` lists "
            f"https://github.com/acme/SecretRotator at {rotator.resolve()}, "
            "and the environment has not checked it out (a repo added while "
            "the pod runs is cloned at its next start). Restart the "
            "environment (`kc env restart`) or clone it (`git clone "
            f"https://github.com/acme/SecretRotator {rotator.resolve()}`), "
            f"then run `kc project setup` in {rotator.resolve()}")
        assert lines[2].startswith("- phase P2: Target `../Charts` is "
                                   "declared but not cloned")


def test_a_run_whose_target_is_declared_and_uncloned_exits_3_before_any_session():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(
            tmp, phases=[("1", "Rotate the secrets", "../SecretRotator")])
        r = ScriptedLoop(slice_dir, [], repo_root=repo)
        with declaring(Path(tmp) / "SecretRotator"):
            assert run_to_exit(r) == 3
        bail = json.loads((slice_dir / "bailout.json").read_text())
        assert bail["reason"] == "target_not_cloned"
        assert bail["question"] is False
        assert "declared but not cloned" in bail["details"]
        assert "kc project setup" in bail["details"]
        assert not r.spawned


def test_a_missing_target_kc_cannot_place_is_the_plan_question_it_was():
    """kc not answering, or config.yaml not declaring the path: the plain
    message, as before — the path may well be the plan's mistake."""
    def kc_down():
        raise ValueError("`kc env describe --output=json` failed (rc=1)")

    for answer in (kc_down, lambda: {Path("/work/Elsewhere"): "u"}):
        with tempfile.TemporaryDirectory() as tmp:
            slice_dir, repo = make_slice(
                tmp, phases=[("1", "Rotate", "../SecretRotator")])
            r = ScriptedLoop(slice_dir, [], repo_root=repo)
            with patched(run_loop, declared_repo_dirs=answer):
                assert run_to_exit(r) == 4
            bail = json.loads((slice_dir / "bailout.json").read_text())
            assert bail["reason"] == "plan_doc" and bail["question"] is True
            assert ("Target `../SecretRotator` is not an existing directory"
                    in bail["details"])
            assert "declared but not cloned" not in bail["details"]


def test_a_done_phase_and_a_cloned_target_never_ask_kc():
    """A done phase's Target is not resolved at all, and a Target on disk
    resolves without kc — only a miss asks."""
    with tempfile.TemporaryDirectory() as tmp:
        sib = make_sibling(tmp)
        slice_dir, repo = make_slice(tmp, phases=[
            ("1", "Rotated once", "../SecretRotator", True),
            ("2", "Chart change", "../Sibling")])
        r = ScriptedLoop(slice_dir, [], repo_root=repo)
        with patched(run_loop, declared_repo_dirs=kc_never_asked):
            phases = r._load_plan()
            assert r._resolve_target("../Sibling").git_root == sib.resolve()
        assert [p.id for p in phases] == ["1", "2"]


def test_a_dry_run_names_a_declared_uncloned_target():
    with tempfile.TemporaryDirectory() as tmp:
        root = dry_run_repo(tmp)
        slice_dir, _ = make_slice(tmp, repo=False)
        (slice_dir / "plan.md").write_text(
            "# plan\n\n" + phase_section("1", "Rotate", "../SecretRotator"))
        loop = RunLoop(slice_dir, resume=False)
        with declaring(Path(tmp) / "SecretRotator"):
            code, out, err = dry_run_from(loop, root)
        assert code == 2
        assert "target=INVALID" in out
        assert ("phase P1: Target `../SecretRotator` is declared but not "
                "cloned") in err


# -- a sibling repo's component as a Target ------------------------------------
#
# Run from /work/Ansible, `kc project list` knows Ansible's components only, so
# `Target: aac-tools` — a component of ../ArgoCDTools — failed the plan check
# as neither a component nor a sibling path (AIWF-8). A bare name the invoking
# repo does not have is now looked up in the sibling repos' own lists.

def kc_lists(**by_repo):
    """A `load_project_dirs` answering per repo, keyed by the repo's
    directory name: its component names (`[PROJECT]` for a repo not named),
    or a string for a repo whose `kc project list` fails with that message.
    `.asked` records every repo it was asked about, in order."""
    asked = []

    def load(cwd):
        cwd = Path(cwd)
        asked.append(cwd.name)
        names = by_repo.get(cwd.name, [PROJECT])
        if isinstance(names, str):
            raise Bailout("protocol_failure", details=names)
        return dict.fromkeys(names, cwd)

    load.asked = asked
    return load


def test_a_sibling_repos_component_resolves_in_that_repo():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        sib = make_sibling(tmp, name="ArgoCDTools")
        make_sibling(tmp, name="Bare", manifest=False)
        r = ScriptedLoop(slice_dir, [], repo_root=repo)
        lists = kc_lists(ArgoCDTools=["root", "aac-tools", "argocd-hook"])
        with patched(run_loop, load_project_dirs=lists):
            r.project_dirs = run_loop.load_project_dirs(repo)
            target = r._resolve_target("aac-tools")
        assert target.kind == "project"
        assert target.git_root == sib and target.gate_cwd == sib
        assert target.gate_argv == ["kc", "project", "test",
                                    "--project", "aac-tools"]
        assert r._executor_where(target) == f" in the sibling repo {sib}"
        outputs = slice_dir / "phases" / "P1"
        assert r._gate_hint(target, outputs, "base123") == (
            f" — through {wrapper_cmd(outputs)}, which runs the driver's own "
            "gate: `kc project test --project aac-tools` and `kc project lint "
            f"--project aac-tools` from {sib}, and both for every other "
            "component the phase's diff touches. "
            f"{run_loop.GATE_REUSE_HINT}. {run_loop.NOTHING_RAN_HINT}")
        # a checkout without a manifest has no components to ask for, and
        # the spec repo beside it has none either
        assert lists.asked == ["repo", "ArgoCDTools"]


def test_the_invoking_repos_components_shadow_a_siblings():
    """Every repo has a `root`; `Target: root` keeps meaning this one's — and
    a hit here never lists a sibling at all."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        make_sibling(tmp, name="ArgoCDTools")
        r = ScriptedLoop(slice_dir, [], repo_root=repo)
        lists = kc_lists(repo=[PROJECT, "root"],
                         ArgoCDTools=["root", "aac-tools"])
        with patched(run_loop, load_project_dirs=lists):
            r.project_dirs = run_loop.load_project_dirs(repo)
            target = r._resolve_target("root")
        assert target.git_root == repo and target.gate_cwd == repo
        assert r._executor_where(target) == ""
        outputs = slice_dir / "phases" / "P1"
        assert r._gate_hint(target, outputs, "base123").startswith(
            f" — through {wrapper_cmd(outputs)}, which runs the driver's own "
            "gate: `kc project test --project root`, and bare")
        assert lists.asked == ["repo"]


def test_a_component_two_siblings_define_must_name_its_repo():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        make_sibling(tmp, name="ArgoCDTools")
        make_sibling(tmp, name="Charts")
        r = ScriptedLoop(slice_dir, [], repo_root=repo)
        with patched(run_loop, load_project_dirs=kc_lists(
                ArgoCDTools=["shared"], Charts=["shared"])):
            r.project_dirs = run_loop.load_project_dirs(repo)
            try:
                r._resolve_target("shared")
            except ValueError as e:
                assert "several sibling repos (ArgoCDTools, Charts)" in str(e)
                assert "`../ArgoCDTools`" in str(e)
            else:
                raise AssertionError("an ambiguous component must not resolve")


def test_a_sibling_kc_cannot_list_is_skipped_and_named():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        sib = make_sibling(tmp, name="ArgoCDTools")
        make_sibling(tmp, name="Broken")
        r = ScriptedLoop(slice_dir, [], repo_root=repo)
        with patched(run_loop, load_project_dirs=kc_lists(
                ArgoCDTools=["aac-tools"], Broken="manifest does not parse")):
            r.project_dirs = run_loop.load_project_dirs(repo)
            assert r._resolve_target("aac-tools").git_root == sib
            try:
                r._resolve_target("nosuch")
            except ValueError as e:
                assert "neither a `kc project list` component" in str(e)
                assert ("siblings searched: ArgoCDTools; `kc project list` "
                        "failed in Broken") in str(e)
            else:
                raise AssertionError("an unknown name must not resolve")
        log = (slice_dir / "log.txt").read_text()
        assert "Broken skipped — manifest does not parse" in log


def test_a_phase_on_a_sibling_repos_component_lands_in_that_repo():
    with tempfile.TemporaryDirectory() as tmp:
        sib = make_sibling(tmp, name="ArgoCDTools")
        slice_dir, repo = make_slice(
            tmp, phases=[("1", "Hook change", "argocd-hook")])
        r = ScriptedLoop(slice_dir,
                         [V["exec_done"], V["review_signoff"], *TAIL],
                         repo_root=repo)
        with patched(run_loop, load_project_dirs=kc_lists(
                ArgoCDTools=["argocd-hook"])):
            assert run_to_exit(r) == 0
        state = load_state(slice_dir)
        assert state["phases"]["1"]["landed"]["root"] == str(sib)
        assert state["bases"][str(sib)] == "main"
        branch_ops = [root for root, c in r.fake_git.calls
                      if c[0] in ("checkout", "merge")
                      and any("phase/074-P1" in a for a in c)]
        assert branch_ops and all(root == sib for root in branch_ops)
        prompt = next(p for role, p in r.prompts if role == "code-writer")
        assert f"out in the sibling repo {sib}." in prompt
        assert f"--project argocd-hook` from {sib}" in prompt
        # the loop-tail sweep covers the sibling's components too
        assert (str(sib), "argocd-hook", "test") in r.sweep_calls


def test_a_component_an_earlier_phase_creates_in_a_sibling_is_a_target():
    """P1 registers `aac-tools` in ../ArgoCDTools and says so; P2 targets it
    before it exists — the dry run and the plan check accept it through the
    declaration — and once P1 has merged the sibling lookup finds it."""
    with tempfile.TemporaryDirectory() as tmp:
        sib = make_sibling(tmp, name="ArgoCDTools")
        slice_dir, repo = make_slice(tmp, phases=[
            ("1", "Stand up aac-tools", "../ArgoCDTools", False,
             "Creates: aac-tools\n"),
            ("2", "Build it out", "aac-tools"),
        ])
        argocd = ["root"]

        def load(cwd):
            names = argocd if Path(cwd).name == "ArgoCDTools" else [PROJECT]
            return dict.fromkeys(names, Path(cwd))

        def register(loop):
            argocd.append("aac-tools")

        with patched(run_loop, load_project_dirs=load):
            dry = RunLoop(slice_dir, resume=False)
            dry.repo_root = repo
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                run_loop.cmd_dry_run(dry)
            assert "target=aac-tools [project]  (created by P1)" \
                in out.getvalue()
            script = [
                ("code-writer", {"outcome": "done", "summary": "built"},
                 register),
                V["review_signoff"], V["exec_done"], V["review_signoff"],
                *TAIL,
            ]
            r = ScriptedLoop(slice_dir, script, repo_root=repo)
            assert run_to_exit(r) == 0
        assert not r.script
        state = load_state(slice_dir)
        assert state["phases"]["2"]["status"] == "merged"
        assert state["phases"]["2"]["landed"]["root"] == str(sib)
        writers = [p for role, p in r.prompts if role == "code-writer"]
        assert f"--project aac-tools` from {sib}" in writers[1]


# -- a shared repo as a Target: the phase's worktree --------------------------
#
# A repo kc marks shared is one clone every environment of the project
# mounts, and whatever branch it stands on is every session's. The spec repo
# is one — and holds the driver's own run record besides. A phase on it works
# in a linked worktree of its own under the scratch root; the shared checkout
# never leaves its base, and the phase merges into it there.

def specs_as_target(tmp):
    """make_slice's specs tree, made resolvable as a sibling Target."""
    (Path(tmp) / "specs" / ".git").mkdir(parents=True, exist_ok=True)
    return "../specs"


def specs_phase(slice_dir, tmp, title="Contract slimming"):
    (slice_dir / "plan.md").write_text(
        "# plan\n\n" + phase_section("1", title, specs_as_target(tmp)))
    return (Path(tmp) / "specs").resolve()


def gated_specs(tmp):
    """The spec tree with a manifest of its own, so its phase has a gate."""
    (Path(tmp) / "specs" / ".kubecoder").mkdir(exist_ok=True)
    (Path(tmp) / "specs" / ".kubecoder" / "project.yaml").write_text(
        "projects: {}\n")


def specs_worktree(loop, pid="1"):
    """Where the fake loop puts P<pid>'s worktree of the specs repo."""
    return loop.worktree_root / "specs" / f"074-P{pid}"


def spec_check_cmd(work, base="base123"):
    """The spec check a spec-repo phase's gate opens with (AIWF-68), as a
    command line: the plugin's own tool, against the review's base."""
    return " ".join(run_loop.spec_check_argv(base, Path(work)))


def spec_check_hint(work, base="base123"):
    return run_loop.SPEC_CHECK_HINT.format(argv=spec_check_cmd(work, base))


def where_clause(work, root, base="main"):
    return (f" in the worktree {work} — a linked checkout of {root}; "
            f"{root}'s own tree stays on {base}, and the plan is edited "
            f"there, never under {work}/slices")


def test_a_shared_repos_phase_is_dispatched_gated_and_checked_in_its_worktree():
    """Every working-tree read and write of the phase goes to the worktree —
    the executor's and the reviewer's pointer, the gate, the dirty checks —
    and the shared checkout is never checked out. No dispatch carries the
    old run-record fence: the record is untracked, so never in a worktree."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        gated_specs(tmp)
        specs = specs_phase(slice_dir, tmp)
        script = [V["exec_done"], V["review_issues"], V["exec_done"],
                  V["review_signoff"], *TAIL]
        r = ScriptedLoop(slice_dir, script, repo_root=repo)
        work = specs_worktree(r)
        with patched(run_loop, shared_repo_dirs=lambda: {specs}):
            assert run_to_exit(r) == 0
        where = where_clause(work, specs)
        for role in ("code-writer", "code-reviewer"):
            prompts = [p for got, p in r.prompts if got == role]
            assert len(prompts) == 2, role
            for prompt in prompts:
                assert where in prompt, role
                assert "git add -A" not in prompt
        writer = next(p for role, p in r.prompts if role == "code-writer")
        assert (f" — through {wrapper_cmd(slice_dir / 'phases' / 'P1')}, "
                f"which runs the driver's own gate: {spec_check_hint(work)}, "
                f"then `kc project test` from {work}. "
                f"{run_loop.GATE_REUSE_HINT}.") in writer
        assert r.gate_cwds and set(r.gate_cwds) == {work}
        adds = [c for root, c in r.fake_git.calls
                if c[:2] == ("worktree", "add")]
        assert adds == [("worktree", "add", "--lock", "--reason",
                         r.fake_git.lock_reasons[0], str(work), "-b",
                         "phase/074-P1", "main")]
        assert r.fake_git.lock_reasons[0].startswith("slice 074 P1: ")
        assert f"pid {os.getpid()}" in r.fake_git.lock_reasons[0]
        dirty_checks = [root for root, c in r.fake_git.calls
                        if c[:2] == ("status", "--porcelain")
                        and str(root) == str(work)]
        assert dirty_checks, "the phase never dirty-checked its worktree"
        assert not [c for root, c in r.fake_git.calls
                    if str(root) == str(specs) and c[0] == "checkout"]
        merges = [c for root, c in r.fake_git.calls
                  if str(root) == str(specs) and c[0] == "merge"]
        assert merges == [("merge", "-m", "slice 074: merge phase/074-P1 (P1)",
                           "phase/074-P1")]
        assert not work.exists() and not r.fake_git.worktrees
        state = load_state(slice_dir)
        assert "worktree" not in state["phases"]["1"]
        assert state["phases"]["1"]["landed"]["root"] == str(specs)
        assert state["shared_repos"] == [str(specs)]


def test_the_spec_repo_works_in_a_worktree_shared_or_not():
    """The tree holding the slice folder is never branched under the run,
    which writes its record there and asserts it on its base before every
    dispatch — kc's flag or no."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        specs = specs_phase(slice_dir, tmp)
        r = ScriptedLoop(slice_dir, [V["exec_done"], V["review_signoff"],
                                     *TAIL], repo_root=repo)
        assert run_to_exit(r) == 0
        assert load_state(slice_dir)["shared_repos"] == []
        assert r.fake_git.lock_reasons
        writer = next(p for role, p in r.prompts if role == "code-writer")
        assert where_clause(specs_worktree(r), specs) in writer


def test_an_unshared_targets_merge_is_the_fast_forward_it_always_was():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r = ScriptedLoop(slice_dir, [V["exec_done"], V["review_signoff"],
                                     *TAIL], repo_root=repo)
        assert run_to_exit(r) == 0
        assert not [c for _, c in r.fake_git.calls if c[0] == "worktree"]
        at_repo = [c for root, c in r.fake_git.calls
                   if str(root) == str(repo)
                   and c[0] in ("checkout", "merge", "branch")
                   and c[:2] != ("branch", "--list")]
        merge = at_repo.index(("merge", "--ff-only", "phase/074-P1"))
        assert at_repo[merge - 1:merge + 2] == [
            ("checkout", "main"), ("merge", "--ff-only", "phase/074-P1"),
            ("branch", "-D", "phase/074-P1")]
        writer = next(p for role, p in r.prompts if role == "code-writer")
        assert " in the worktree " not in writer


def test_a_worktree_left_dirty_at_the_merge_bails():
    def leaves_work_behind(loop):
        loop.fake_git.dirty_roots[str(specs_worktree(loop))] = " M api.md\n"

    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        specs = specs_phase(slice_dir, tmp)
        r = ScriptedLoop(slice_dir, [V["exec_done"],
                                     (*V["review_signoff"],
                                      leaves_work_behind)],
                         repo_root=repo)
        with patched(run_loop, shared_repo_dirs=lambda: {specs}):
            assert run_to_exit(r) == 3
        bail = json.loads((slice_dir / "bailout.json").read_text())
        assert bail["reason"] == "protocol_failure"
        assert "worktree dirty at merge" in bail["details"]
        assert str(specs_worktree(r)) in bail["details"]
        # the bail leaves the worktree for the resume, and the shared
        # checkout was never off its base to restore
        assert specs_worktree(r).exists()
        assert "worktree" in load_state(slice_dir)["phases"]["1"]


def resume_state(target, stage="review"):
    return {
        "slice": "074_test_slice", "created_at": "t", "orchestrator": None,
        "run_phase": "phases", "bases": {}, "known_phases": ["1"],
        "phases": {"1": {"status": "in_progress", "stage": stage,
                         "branch": "phase/074-P1", "target": target,
                         "executor_rounds": 1, "gate_fix_rounds": 0,
                         "review_rounds": 0, "gate_runs": 0,
                         "gate_green_commit": None, "gate_green_log": None,
                         "reviewed_head": None}},
        "generation": 0, "test_rounds": 0, "consult_seq": 0,
        "in_flight": None, "history": [],
    }


def test_a_resume_resets_a_shared_repos_phase_in_its_worktree():
    """The dead round's uncommitted work goes with a plain `reset --hard` —
    in the worktree, where nothing but the phase writes. A code repo's
    resume resets its own tree, as ever."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        specs_phase(slice_dir, tmp)
        (slice_dir / "state.json").write_text(
            json.dumps(resume_state("../specs")))
        r = ScriptedLoop(slice_dir, [V["review_signoff"], *TAIL],
                         resume=True, repo_root=repo)
        r.fake_git.branches.add("phase/074-P1")
        work = specs_worktree(r)
        work.mkdir(parents=True)
        (work / ".git").write_text("gitdir: a fake's\n")
        r.fake_git.branch_at[str(work)] = "phase/074-P1"
        assert run_to_exit(r) == 0
        assert [(str(root), c) for root, c in r.fake_git.mutations("reset")] \
            == [(str(work), ("reset", "--hard", "HEAD"))]
        assert not r.fake_git.mutations("restore")
        assert not [c for _, c in r.fake_git.calls
                    if c[:2] == ("worktree", "add")], "reused, not re-added"
        assert f"resuming at stage review in {work}" \
            in (slice_dir / "log.txt").read_text()

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


# -- a resume sets a dead round's uncommitted work aside (AIWF-58) -------------

# A dead round's work as `git diff HEAD` answers it — the trailing blank
# context line and the final newline are what `git apply` reads, so the
# set-aside keeps them.
DEAD_ROUND_DIFF = ("diff --git a/src/api.py b/src/api.py\n"
                   "--- a/src/api.py\n+++ b/src/api.py\n"
                   "@@ -1,2 +1,3 @@\n def handler():\n+    return 1\n \n")


def set_aside_dir(slice_dir):
    return slice_dir / "phases" / "P1" / "set-aside"


def set_aside_diff(patch):
    """The driver's `git diff` that writes the set-aside patch to `patch`."""
    return ("diff", "--binary", "--no-ext-diff", "--no-textconv",
            "--no-color", f"--output={patch}", "HEAD")


def commits_round(root):
    """A code-writer effect: the round commits its work, leaving `root`
    clean — the fake's `reset` leaves an unmodelled tree as it found it."""
    def effect(loop):
        loop.fake_git.dirty_roots[str(root)] = ""
    return effect


def dead_round_in(loop, root, untracked=()):
    """`root` as a round that died uncommitted left it: DEAD_ROUND_DIFF
    tracked, and `untracked` on disk (path → text)."""
    lines = [" M src/api.py"] + [f"?? {p}" for p in untracked]
    loop.fake_git.dirty_roots[str(root)] = "\n".join(lines) + "\n"
    loop.fake_git.uncommitted[str(root)] = DEAD_ROUND_DIFF
    loop.fake_git.untracked[str(root)] = list(untracked)
    for rel, text in dict(untracked).items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)


def calls_at(loop):
    return [(str(root), c) for root, c in loop.fake_git.calls]


def test_a_resume_sets_the_dead_rounds_work_aside_before_the_reset():
    """SecretRotator slice 051: the writer hit the session cap with its test
    edits uncommitted, and the resume's reset dropped them. The reset
    stays; the patch, byte for byte, and copies of the untracked files go
    under the phase's `set-aside/` first, and the next writer is told where
    — and that the dead round's done-record may describe the patch."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        (slice_dir / "state.json").write_text(
            json.dumps(resume_state(PROJECT, stage="executor")))
        r = ScriptedLoop(slice_dir, [(*V["exec_done"], commits_round(repo)),
                                     V["review_signoff"], *TAIL],
                         resume=True, repo_root=repo)
        r.fake_git.branches.add("phase/074-P1")
        dead_round_in(r, repo, {"notes.txt": "half a thought\n",
                                "tests/new/test_api.py": "def test(): ...\n"})
        os.symlink("notes.txt", repo / "link.txt")
        r.fake_git.untracked[str(repo)].append("link.txt")
        assert run_to_exit(r) == 0
        out = set_aside_dir(slice_dir)
        patch, copies = out / "r1.patch", out / "r1-untracked"
        assert (out / ".gitignore").read_text() == "*\n"
        assert patch.read_text() == DEAD_ROUND_DIFF
        assert (copies / "notes.txt").read_text() == "half a thought\n"
        assert (copies / "tests" / "new" / "test_api.py").read_text() \
            == "def test(): ...\n"
        assert os.readlink(copies / "link.txt") == "notes.txt"
        assert (repo / "notes.txt").exists(), "the untracked stay in the tree"
        calls = calls_at(r)
        reset = calls.index((str(repo), ("reset", "--hard", "HEAD")))
        saved = calls.index((str(repo), set_aside_diff(patch)))
        listed = calls.index((str(repo), ("ls-files", "--others",
                                          "--exclude-standard", "-z")))
        assert saved < reset and listed < reset
        assert ("[P1] the dead round's uncommitted work set aside before the "
                f"reset: {patch}; 3 untracked file(s) copied to {copies} "
                "(still in the tree)") in (slice_dir / "log.txt").read_text()
        writer = next(p for role, p in r.prompts if role == "code-writer")
        assert ("Code-writer round 1 of this phase died with uncommitted "
                "work") in writer
        assert f"`{patch}` is its `git diff HEAD`, and `{copies}` holds " \
            "copies of its 3 untracked files" in writer
        assert "may describe the patch rather than the tree" in writer
        assert "set_aside" not in load_state(slice_dir)["phases"]["1"]


def test_a_shared_repos_resume_sets_aside_from_its_worktree():
    """The second resume site: the worktree is the tree being reset, so it
    is the one read — never the shared checkout, which stays on its base."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        specs = specs_phase(slice_dir, tmp)
        (slice_dir / "state.json").write_text(
            json.dumps(resume_state("../specs", stage="executor")))
        r = ScriptedLoop(slice_dir, [V["exec_done"], V["review_signoff"],
                                     *TAIL], resume=True, repo_root=repo)
        r.fake_git.branches.add("phase/074-P1")
        work = specs_worktree(r)
        work.mkdir(parents=True)
        (work / ".git").write_text("gitdir: a fake's\n")
        r.fake_git.branch_at[str(work)] = "phase/074-P1"
        dead_round_in(r, work, {"draft.md": "draft\n"})
        r.script[0] = (*V["exec_done"], commits_round(work))
        assert run_to_exit(r) == 0
        out = set_aside_dir(slice_dir)
        assert (out / "r1.patch").read_text() == DEAD_ROUND_DIFF
        assert (out / "r1-untracked" / "draft.md").read_text() == "draft\n"
        calls = calls_at(r)
        assert calls.index((str(work), set_aside_diff(out / "r1.patch"))) \
            < calls.index((str(work), ("reset", "--hard", "HEAD")))
        assert not [c for root, c in calls if root == str(specs)
                    and (c[0] == "ls-files" or "--output=" in " ".join(c))]
        writer = next(p for role, p in r.prompts if role == "code-writer")
        assert f"`{out / 'r1.patch'}` is its `git diff HEAD`" in writer


def test_a_resume_over_a_clean_tree_sets_nothing_aside():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        (slice_dir / "state.json").write_text(
            json.dumps(resume_state(PROJECT, stage="executor")))
        r = ScriptedLoop(slice_dir, [V["exec_done"], V["review_signoff"],
                                     *TAIL], resume=True, repo_root=repo)
        r.fake_git.branches.add("phase/074-P1")
        assert run_to_exit(r) == 0
        assert r.fake_git.mutations("reset"), "the reset runs as ever"
        assert not set_aside_dir(slice_dir).exists()
        assert not [c for _, c in r.fake_git.calls
                    if c[0] == "ls-files" or "--output=" in " ".join(c)]
        writer = next(p for role, p in r.prompts if role == "code-writer")
        assert "set it aside" not in writer
        assert "uncommitted work set aside" \
            not in (slice_dir / "log.txt").read_text()


def test_a_reattaching_resume_sets_nothing_aside():
    """The reattached session needs its tree as it left it: no reset, so
    nothing to save from one."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        state = resume_state(PROJECT, stage="executor")
        state["in_flight"] = {
            "phase": "1", "role": "code-writer", "round": 1,
            "verdict_path": str(slice_dir / "phases" / "P1"
                                / "executor_result_r1.json"),
            "session": "sess-crashed", "started_at": "t"}
        (slice_dir / "state.json").write_text(json.dumps(state))
        r = ScriptedLoop(slice_dir, [(*V["exec_done"], commits_round(repo)),
                                     V["review_signoff"], *TAIL],
                         resume=True, repo_root=repo)
        r.fake_git.branches.add("phase/074-P1")
        dead_round_in(r, repo, {"notes.txt": "half a thought\n"})
        assert run_to_exit(r) == 0
        assert r.spawned[0][4] == "sess-crashed"
        assert not r.fake_git.mutations("reset")
        assert not set_aside_dir(slice_dir).exists()
        assert "set_aside" not in load_state(slice_dir)["phases"]["1"]


def test_the_set_aside_line_reaches_the_first_writer_after_the_resume_only():
    """A red gate's fix round is a second writer in the same run: the note
    was the first one's, and the state no longer holds it."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        (slice_dir / "state.json").write_text(
            json.dumps(resume_state(PROJECT, stage="executor")))
        r = ScriptedLoop(slice_dir, [(*V["exec_done"], commits_round(repo)),
                                     V["exec_done"], V["review_signoff"],
                                     *TAIL],
                         resume=True, repo_root=repo, gates=[False, True])
        r.fake_git.branches.add("phase/074-P1")
        dead_round_in(r, repo)
        assert run_to_exit(r) == 0
        writers = [p for role, p in r.prompts if role == "code-writer"]
        assert len(writers) == 2
        assert "may describe the patch rather than the tree" in writers[0]
        assert "set it aside" not in writers[1]
        # no untracked files: no copies, and the prompt names none
        assert "untracked" not in writers[0].split("Code-writer round 1")[1]
        assert not (set_aside_dir(slice_dir) / "r1-untracked").exists()
        assert "set_aside" not in load_state(slice_dir)["phases"]["1"]


def test_a_set_aside_never_overwrites_an_earlier_one():
    """A second resume of the same round — the first set-aside saved, the
    reset or the dispatch after it failed — takes the next free name."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        out = set_aside_dir(slice_dir)
        out.mkdir(parents=True)
        (out / "r1.patch").write_text("the first resume's\n")
        (out / "r1-2-untracked").mkdir()
        (slice_dir / "state.json").write_text(
            json.dumps(resume_state(PROJECT, stage="executor")))
        r = ScriptedLoop(slice_dir, [(*V["exec_done"], commits_round(repo)),
                                     V["review_signoff"], *TAIL],
                         resume=True, repo_root=repo)
        r.fake_git.branches.add("phase/074-P1")
        dead_round_in(r, repo)
        assert run_to_exit(r) == 0
        assert (out / "r1.patch").read_text() == "the first resume's\n"
        assert (out / "r1-3.patch").read_text() == DEAD_ROUND_DIFF
        writer = next(p for role, p in r.prompts if role == "code-writer")
        assert f"`{out / 'r1-3.patch'}` is its `git diff HEAD`." in writer


def test_a_set_aside_that_fails_bails_before_the_reset():
    """Losing the work is what the set-aside is for, so a save that cannot
    be made stops the resume rather than resetting — a git failure and a
    copy that cannot be made alike."""
    def git_fails(loop, slice_dir, repo):
        dead_round_in(loop, repo)
        loop.fake_git.fails.add(
            set_aside_diff(set_aside_dir(slice_dir) / "r1.patch"))

    def copy_fails(loop, slice_dir, repo):
        dead_round_in(loop, repo)
        loop.fake_git.untracked[str(repo)] = ["gone.txt"]   # not on disk

    for breaks in (git_fails, copy_fails):
        with tempfile.TemporaryDirectory() as tmp:
            slice_dir, repo = make_slice(tmp)
            (slice_dir / "state.json").write_text(
                json.dumps(resume_state(PROJECT, stage="executor")))
            r = ScriptedLoop(slice_dir, [], resume=True, repo_root=repo)
            r.fake_git.branches.add("phase/074-P1")
            breaks(r, slice_dir, repo)
            assert run_to_exit(r) == 3, breaks.__name__
            bail = json.loads((slice_dir / "bailout.json").read_text())
            assert bail["reason"] == "protocol_failure"
            assert bail["phase"] == "1"
            assert "could not set the dead round's uncommitted work in " \
                f"{repo} aside" in bail["details"]
            assert "nothing was reset" in bail["details"]
            assert not r.fake_git.mutations("reset"), breaks.__name__
            assert not r.prompts
            assert "set_aside" not in load_state(slice_dir)["phases"]["1"]


# -- which repos are shared -----------------------------------------------------

def test_shared_repo_dirs_reads_kcs_repos_and_fails_with_the_cause():
    good = subprocess.CompletedProcess([], 0, stdout=json.dumps({
        "sections": [], "repos": [
            {"url": "u1", "dir": "/work/App", "shared": False, "ref": None},
            {"url": "u2", "dir": "/work/AppSpecs", "shared": True,
             "ref": None},
            {"url": "u3", "dir": "/work/Ref", "shared": True},
            {"url": "u4", "shared": True},
            "not a repo"]}), stderr="")
    with patched(run_loop.subprocess, run=lambda *a, **kw: good):
        assert REAL_SHARED_REPO_DIRS() == {Path("/work/AppSpecs").resolve(),
                                           Path("/work/Ref").resolve()}
    for answer, why in [
            (subprocess.CompletedProcess([], 1, stdout="", stderr="no pod"),
             "failed (rc=1): no pod"),
            (subprocess.CompletedProcess([], 0, stdout='{"sections": []}',
                                         stderr=""),
             "carries no `repos` list"),
            (subprocess.CompletedProcess([], 0, stdout="{torn", stderr=""),
             "invalid JSON")]:
        with patched(run_loop.subprocess, run=lambda *a, _r=answer, **kw: _r):
            try:
                REAL_SHARED_REPO_DIRS()
            except ValueError as e:
                assert "kc env describe --output=json" in str(e)
                assert why in str(e), str(e)
            else:
                raise AssertionError(f"{why} must be a ValueError")


def test_a_shared_primary_repo_is_refused_before_anything_runs():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r = ScriptedLoop(slice_dir, [], repo_root=repo)
        with patched(run_loop, shared_repo_dirs=lambda: {repo.resolve()}):
            assert run_to_exit(r) == 3
        bail = json.loads((slice_dir / "bailout.json").read_text())
        assert bail["reason"] == "protocol_failure"
        assert "a shared primary repo is not supported" in bail["details"]
        assert not r.spawned and not r.fake_git.specs_ops()


def test_kc_not_saying_which_repos_are_shared_stops_the_run():
    """Without the answer a phase could branch a shared tree in place."""
    def broken():
        raise ValueError("`kc env describe --output=json` failed (rc=1): "
                         "no pod")

    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r = ScriptedLoop(slice_dir, [], repo_root=repo)
        with patched(run_loop, shared_repo_dirs=broken):
            assert run_to_exit(r) == 3
        bail = json.loads((slice_dir / "bailout.json").read_text())
        assert bail["reason"] == "protocol_failure"
        assert "which repos of this environment are shared" in bail["details"]
        assert "`kc env describe --output=json` failed" in bail["details"]
        assert not r.spawned


def test_a_resume_reads_the_shared_repos_the_run_recorded():
    """A phase that began in a worktree finishes in one, whatever kc says
    now — and kc is not asked."""
    def never():
        raise AssertionError("a resume with a record must not ask kc")

    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        other = Path(tmp) / "elsewhere"
        state = resume_state(PROJECT, stage="executor")
        state["shared_repos"] = [str(other)]
        (slice_dir / "state.json").write_text(json.dumps(state))
        r = ScriptedLoop(slice_dir, [V["exec_done"], V["review_signoff"],
                                     *TAIL], resume=True, repo_root=repo)
        r.fake_git.branches.add("phase/074-P1")
        with patched(run_loop, shared_repo_dirs=never):
            assert run_to_exit(r) == 0
        assert r._shared_dirs() == {other}
        assert load_state(slice_dir)["shared_repos"] == [str(other)]


# -- a shared repo's phase over real git ---------------------------------------
#
# The worktree and the merge are git's own behaviour — a locked registration,
# a refused fast-forward, a conflict — so these run it for real: sessions,
# gates and kc stay scripted, every git call is git's.

@contextlib.contextmanager
def plain_git():
    """Real git, isolated from the machine's config and with an identity to
    commit as — set in os.environ, since the driver's git and the tests'
    run as subprocesses that inherit it."""
    env = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "Test",
           "GIT_COMMITTER_EMAIL": "t@example.invalid"}
    saved = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def sh(cwd, *args):
    """git in `cwd`, checked; its stdout."""
    return subprocess.run(["git", *args], cwd=cwd, check=True,
                          capture_output=True, text=True).stdout.strip()


class RealGitLoop(ScriptedLoop):
    """ScriptedLoop over real git. Nothing is fetched: the repos have no
    origin."""

    def __init__(self, slice_dir, script, **kw):
        super().__init__(slice_dir, script, **kw)
        self.git = types.MethodType(RunLoop.git, self)
        self.git_ok = types.MethodType(RunLoop.git_ok, self)
        self.git_raw = types.MethodType(RunLoop.git_raw, self)

    def _fetch_origin(self, root):
        pass

    def _git_attempt(self, *args, root):
        return RunLoop._git_attempt(self, *args, root=root)


def real_shared_slice(tmp, body=""):
    """A slice whose one phase targets the specs repo, over real git: the
    specs and the code repo each a repo with everything committed on main,
    the specs carrying a manifest (so the phase has a gate) and api.md, ten
    lines the phase and the other writers of these tests edit. The project
    runs neither a test nor a doc phase and never pushes, so a run ends at
    its completion consult."""
    slice_dir, repo = make_slice(
        tmp, phases=[("1", "Contract", "../specs", False, body)],
        config=rc(test=False, doc=False, push=False))
    specs = (Path(tmp) / "specs").resolve()
    shutil.rmtree(specs / ".git")
    gated_specs(tmp)
    (specs / "api.md").write_text("".join(f"line {n}\n" for n in range(1, 11)))
    for where in (specs, repo):
        sh(where, "init", "-q", "-b", "main")
        sh(where, "add", "-A")
        sh(where, "commit", "-qm", "init")
    return slice_dir, repo, specs


def edit_line(path, n, text):
    lines = path.read_text().splitlines(keepends=True)
    lines[n - 1] = text + "\n"
    path.write_text("".join(lines))


def phase_work(*also):
    """A script step's effect: the writer changes api.md's first line in its
    worktree and commits it; then each of `also`, called with the loop."""
    def effect(loop):
        work = Path(loop.state["phases"]["1"]["worktree"])
        edit_line(work / "api.md", 1, "line 1, the phase's")
        sh(work, "commit", "-qam", "P1: the contract")
        for step in also:
            step(loop)
    return effect


def base_commit(n, text):
    """Another session's commit of api.md's line `n` on the shared base."""
    def step(loop):
        edit_line(loop.spec_root / "api.md", n, text)
        sh(loop.spec_root, "commit", "-qm", "another session's", "--",
           "api.md")
    return step


def base_edit(n, text):
    """Another writer's edit of api.md's line `n`, left uncommitted in the
    shared checkout."""
    def step(loop):
        edit_line(loop.spec_root / "api.md", n, text)
    return step


def shared_run(slice_dir, repo, specs, *also, loop=RealGitLoop, **kw):
    """One phase on the shared specs repo, its writer doing `phase_work`."""
    r = loop(slice_dir, [(*V["exec_done"], phase_work(*also)),
                         V["review_signoff"], V["consult_complete"]],
             repo_root=repo, **kw)
    with patched(run_loop, shared_repo_dirs=lambda: {specs}):
        code = run_to_exit(r)
    return r, code


def subjects(specs):
    return sh(specs, "log", "--format=%s", "main").splitlines()


def test_a_shared_repos_phase_fast_forwards_its_base_and_leaves_nothing():
    if shutil.which("git") is None:
        return
    with tempfile.TemporaryDirectory() as tmp, plain_git():
        slice_dir, repo, specs = real_shared_slice(tmp)
        seen = {}

        def looks(loop):
            seen["branch"] = sh(specs, "rev-parse", "--abbrev-ref", "HEAD")
            seen["listed"] = sh(specs, "worktree", "list", "--porcelain")

        r, code = shared_run(slice_dir, repo, specs, looks)
        assert code == 0
        work = r.worktree_root / "specs" / "074-P1"
        # while the phase worked, the shared checkout stayed on main and
        # the worktree was registered locked, on the phase's branch
        assert seen["branch"] == "main"
        assert f"worktree {work}\n" in seen["listed"]
        assert "branch refs/heads/phase/074-P1" in seen["listed"]
        assert "locked slice 074 P1: " in seen["listed"]
        assert r.gate_cwds == [work]
        # a fast-forward: no merge commit, the phase's commit on main
        assert not sh(specs, "log", "--merges", "--format=%H", "main")
        assert subjects(specs)[:2] == ["slice 074: stamp P1 done",
                                       "P1: the contract"]
        assert (specs / "api.md").read_text().startswith(
            "line 1, the phase's\n")
        assert "merged into main in specs (fast-forward)" \
            in (slice_dir / "log.txt").read_text()
        # nothing left behind: the worktree, its registration, the branch
        assert not work.exists()
        assert sh(specs, "worktree", "list", "--porcelain").count(
            "worktree ") == 1
        assert not sh(specs, "branch", "--list", "phase/074-P1")
        ps = load_state(slice_dir)["phases"]["1"]
        assert ps["status"] == "merged" and "worktree" not in ps
        assert ps["landed"]["head"] == sh(specs, "rev-parse", "main~1")


def test_a_base_that_moved_under_the_phase_gets_a_merge_commit():
    """The shared base moves with every session's commit; the branch is
    merged, never rebased — the reviewed commits keep their shas."""
    if shutil.which("git") is None:
        return
    with tempfile.TemporaryDirectory() as tmp, plain_git():
        slice_dir, repo, specs = real_shared_slice(tmp)
        r, code = shared_run(slice_dir, repo, specs,
                             base_commit(10, "line 10, another session's"))
        assert code == 0
        merges = sh(specs, "log", "--merges", "--format=%s", "main")
        assert merges == "slice 074: merge phase/074-P1 (P1)"
        text = (specs / "api.md").read_text()
        assert "line 1, the phase's" in text
        assert "line 10, another session's" in text
        ps = load_state(slice_dir)["phases"]["1"]
        assert ps["landed"]["head"] == ps["reviewed_head"]
        assert sh(specs, "merge-base", "--is-ancestor", ps["reviewed_head"],
                  "main") == ""
        assert "merged into main in specs (a merge commit — main had moved)" \
            in (slice_dir / "log.txt").read_text()


def test_a_shared_repos_landed_base_is_where_the_branch_forked():
    """The landed range starts where the branch forked from the base, taken
    before the merge (AIWF-104) — after it, the merge base is the branch's
    own head — whether the merge fast-forwards or makes a merge commit."""
    if shutil.which("git") is None:
        return
    for also in ((), (base_commit(10, "line 10, another session's"),)):
        with tempfile.TemporaryDirectory() as tmp, plain_git():
            slice_dir, repo, specs = real_shared_slice(tmp)
            r, code = shared_run(slice_dir, repo, specs, *also)
            assert code == 0
            landed = load_state(slice_dir)["phases"]["1"]["landed"]
            # the phase's one commit, from the commit it was made on
            assert landed["base"] \
                == sh(specs, "rev-parse", f"{landed['head']}^")
            assert sh(specs, "log", "--format=%s",
                      f"{landed['base']}..{landed['head']}") \
                == "P1: the contract"


def test_another_writers_edit_in_the_merges_way_is_swept_and_the_merge_goes_on():
    if shutil.which("git") is None:
        return
    with tempfile.TemporaryDirectory() as tmp, plain_git():
        slice_dir, repo, specs = real_shared_slice(tmp)
        r, code = shared_run(slice_dir, repo, specs,
                             base_edit(10, "line 10, left uncommitted"))
        assert code == 0
        assert "slice 074: edits left uncommitted in specs, swept at P1's " \
               "merge" in subjects(specs)
        text = (specs / "api.md").read_text()
        assert "line 1, the phase's" in text
        assert "line 10, left uncommitted" in text
        assert not sh(specs, "status", "--porcelain", "--", "api.md")
        assert "swept into main: api.md" in (slice_dir / "log.txt").read_text()


def test_a_conflict_bails_for_a_hand_merge_and_the_resume_stamps_it():
    if shutil.which("git") is None:
        return
    with tempfile.TemporaryDirectory() as tmp, plain_git():
        slice_dir, repo, specs = real_shared_slice(tmp)
        r, code = shared_run(slice_dir, repo, specs,
                             base_commit(1, "line 1, another session's"))
        assert code == 3
        bail = json.loads((slice_dir / "bailout.json").read_text())
        assert bail["reason"] == "blocked" and bail["phase"] == "1"
        assert "Merge phase/074-P1 into main in" in bail["details"]
        assert "CONFLICT (content): Merge conflict in api.md" in bail["details"]
        # aborted: the shared checkout as it stood, the worktree kept
        assert not (specs / ".git" / "MERGE_HEAD").exists()
        assert not sh(specs, "status", "--porcelain", "--", "api.md")
        work = r.worktree_root / "specs" / "074-P1"
        assert work.exists()
        assert load_state(slice_dir)["phases"]["1"]["stage"] == "merging"

        # the operator merges by hand
        subprocess.run(["git", "merge", "-q", "phase/074-P1"], cwd=specs,
                       capture_output=True)
        (specs / "api.md").write_text(
            "line 1, as the operator settled it\n"
            + "".join(f"line {n}\n" for n in range(2, 11)))
        sh(specs, "add", "api.md")
        sh(specs, "commit", "-qm", "merge P1 by hand")

        r2 = RealGitLoop(slice_dir, [V["consult_complete"]], resume=True,
                         repo_root=repo)
        with patched(run_loop, shared_repo_dirs=lambda: {specs}):
            assert run_to_exit(r2) == 0
        ps = load_state(slice_dir)["phases"]["1"]
        assert ps["status"] == "merged" and "worktree" not in ps
        assert not work.exists()
        assert not sh(specs, "branch", "--list", "phase/074-P1")
        assert subjects(specs)[0] == "slice 074: stamp P1 done"
        assert "already merged into main" in (slice_dir / "log.txt").read_text()
        assert load_state(slice_dir)["bailouts"][0]["reported"] is True


def test_the_slice_tree_is_taken_back_out_of_the_branch_and_logged():
    """A writer that greps for plan.md finds the worktree's copy too. What
    the branch changed under slices/ goes back to the fork in one commit,
    and the gate runs again on the head that moved."""
    def misplaces(loop):
        work = Path(loop.state["phases"]["1"]["worktree"])
        plan = work / "slices" / "074_test_slice" / "plan.md"
        plan.write_text(plan.read_text() + "\n**Done (P1).** misplaced\n")
        stray = work / "slices" / "075_other" / "notes.md"
        stray.parent.mkdir(parents=True)
        stray.write_text("not this phase's\n")
        sh(work, "add", "-A")
        sh(work, "commit", "-qm", "P1: the done-record, in the wrong copy")

    if shutil.which("git") is None:
        return
    with tempfile.TemporaryDirectory() as tmp, plain_git():
        slice_dir, repo, specs = real_shared_slice(tmp)
        r, code = shared_run(slice_dir, repo, specs, misplaces)
        assert code == 0
        assert ("slice 074: slices/** taken back out of phase/074-P1 — the "
                "slice tree is never a phase's deliverable") in subjects(specs)
        shipped = sh(specs, "show", "main:slices/074_test_slice/plan.md")
        assert "misplaced" not in shipped
        assert not sh(specs, "ls-tree", "-r", "--name-only", "main", "--",
                      "slices/075_other")
        assert "line 1, the phase's" in (specs / "api.md").read_text()
        log = (slice_dir / "log.txt").read_text()
        assert "changed the slice tree — taken back out" in log
        assert "slices/074_test_slice/plan.md" in log
        assert "slices/075_other/notes.md" in log
        assert len(r.gate_cwds) == 2, "the moved head is gated again"


def test_a_resume_reuses_the_worktree_or_adds_it_again_over_a_stale_registration():
    """The registration lives in the shared git dir, locked: another
    environment sees it pointing at nothing, and so does this one after a
    Reset wipes the scratch root. Either way the resume unlocks and prunes
    what holds the branch and adds the worktree again from the branch —
    the committed work is all there."""
    if shutil.which("git") is None:
        return
    with tempfile.TemporaryDirectory() as tmp, plain_git():
        slice_dir, repo, specs = real_shared_slice(tmp)
        r = RealGitLoop(slice_dir, [], repo_root=repo)
        branch = "phase/074-P1"
        ps = {"status": "pending", "stage": None, "executor_rounds": 1}

        def ensure(existing=branch):
            with patched(run_loop, WORKTREE_ROOT=r.worktree_root):
                return r._ensure_worktree("1", ps, specs, "main", branch,
                                          existing)

        work = ensure(existing="")
        assert work == r.worktree_root / "specs" / "074-P1"
        assert ps["worktree"] == str(work)
        listed = sh(specs, "worktree", "list", "--porcelain")
        assert f"branch refs/heads/{branch}" in listed
        assert "locked slice 074 P1: " in listed
        edit_line(work / "api.md", 1, "committed")
        sh(work, "commit", "-qam", "the phase's work")
        edit_line(work / "api.md", 2, "left uncommitted")
        (work / "notes").mkdir()
        (work / "notes" / "new.md").write_text("an untracked draft\n")
        ps.update(status="in_progress", stage="review")

        # reused, reset to its last commit...
        assert ensure() == work
        text = (work / "api.md").read_text()
        assert "committed" in text and "left uncommitted" not in text
        # ...once what the reset dropped is set aside: a patch git applies
        # back, the untracked file copied and still in the tree, and nothing
        # of it showing in the spec repo's own status
        out = set_aside_dir(slice_dir)
        assert [rec["patch"] for rec in ps.pop("set_aside")] \
            == [str(out / "r1.patch")]
        assert (out / "r1-untracked" / "notes" / "new.md").read_text() \
            == "an untracked draft\n"
        assert (work / "notes" / "new.md").exists()
        assert "set-aside" not in sh(specs, "status", "--porcelain",
                                     "--untracked-files=all")
        sh(work, "apply", str(out / "r1.patch"))
        assert (work / "api.md").read_text() == text.replace(
            "line 2\n", "left uncommitted\n")
        # ...but as it stands under a reattach
        edit_line(work / "api.md", 2, "left uncommitted")
        r._reattach = {"phase": "1", "session": "sess-1"}
        assert ensure() == work
        assert "left uncommitted" in (work / "api.md").read_text()
        r._reattach = None

        # a Reset wiped the scratch root: the locked registration stays
        shutil.rmtree(r.worktree_root)
        assert ensure() == work
        assert "committed" in (work / "api.md").read_text()

        # another environment's registration holds the branch, at a path
        # that does not exist here
        sh(specs, "worktree", "unlock", str(work))
        sh(specs, "worktree", "remove", "--force", str(work))
        theirs = Path(tmp) / "env-b" / "074-P1"
        sh(specs, "worktree", "add", "-q", "--lock", "--reason",
           "slice 074 P1: env-b host-b pid 1", str(theirs), branch)
        shutil.move(str(theirs), str(Path(tmp) / "gone"))
        assert ensure() == work
        listed = sh(specs, "worktree", "list", "--porcelain")
        assert str(theirs) not in listed
        assert f"worktree {work}\n" in listed
        assert "committed" in (work / "api.md").read_text()


def test_the_shared_checkout_itself_on_the_branch_is_never_touched():
    """A hand checkout, or a run of a plugin that still branched the tree in
    place: never removed or moved — a stop."""
    if shutil.which("git") is None:
        return
    with tempfile.TemporaryDirectory() as tmp, plain_git():
        slice_dir, repo, specs = real_shared_slice(tmp)
        r = RealGitLoop(slice_dir, [], repo_root=repo)
        sh(specs, "checkout", "-qb", "phase/074-P1")
        ps = {"status": "in_progress", "stage": "review"}
        with patched(run_loop, WORKTREE_ROOT=r.worktree_root):
            try:
                r._ensure_worktree("1", ps, specs, "main", "phase/074-P1",
                                   "phase/074-P1")
            except Bailout as e:
                assert e.reason == "blocked"
                assert "checked out in place" in e.details
            else:
                raise AssertionError("the shared checkout's branch was taken")
        assert specs.exists()
        assert sh(specs, "rev-parse", "--abbrev-ref", "HEAD") == "phase/074-P1"


def test_what_stands_in_a_merges_way_is_read_off_either_refusal():
    tracked = ("Updating c4a5e87..6cfb80c\n"
               "error: Your local changes to the following files would be "
               "overwritten by merge:\n\tapi.md\n\tdocs/b c.md\n"
               "Please commit your changes or stash them before you merge.\n"
               "Aborting")
    untracked = ("error: The following untracked working tree files would be "
                 "overwritten by merge:\n\tnew.md\n"
                 "Please move or remove them before you merge.\nAborting")
    staged = ("error: Your local changes to the following files would be "
              "overwritten by merge:\n  staged.md\n"
              "Merge with strategy ort failed.")
    assert run_loop.overwritten_paths(tracked) == ["api.md", "docs/b c.md"]
    assert run_loop.overwritten_paths(untracked) == ["new.md"]
    assert run_loop.overwritten_paths(staged) == ["staged.md"]
    assert run_loop.overwritten_paths(
        "CONFLICT (content): Merge conflict in api.md\n"
        "Automatic merge failed; fix conflicts and then commit the "
        "result.") == []


def test_a_merge_waits_out_another_gits_index_lock_and_gives_up_at_the_cap():
    lock = (128, "error: Unable to create '/specs/.git/index.lock': File "
                 "exists.\nfatal: Unable to write index.")
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        specs = specs_phase(slice_dir, tmp)
        r = ScriptedLoop(slice_dir, [V["exec_done"], V["review_signoff"],
                                     *TAIL], repo_root=repo)
        r.fake_git.attempts = [lock, lock]
        with patched(run_loop, shared_repo_dirs=lambda: {specs}):
            assert run_to_exit(r) == 0
        assert r.sleeps == [run_loop.INDEX_LOCK_WAIT] * 2

    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        specs = specs_phase(slice_dir, tmp)
        r = ScriptedLoop(slice_dir, [V["exec_done"], V["review_signoff"]],
                         repo_root=repo)
        r.fake_git.attempts = [lock] * run_loop.MERGE_ATTEMPTS
        with patched(run_loop, shared_repo_dirs=lambda: {specs}):
            assert run_to_exit(r) == 3
        bail = json.loads((slice_dir / "bailout.json").read_text())
        assert bail["reason"] == "protocol_failure"
        assert f"in {run_loop.MERGE_ATTEMPTS} attempts" in bail["details"]
        assert "index.lock" in bail["details"]


# -- the shared spec tree -----------------------------------------------------
#
# That one working tree is shared with every parallel session — other run
# loops, plan loops, the operator's own. The run never moves it; what is left
# here is the run leaving the trees it does branch as it found them, never
# adopting another run's abandoned phase branch as its base, and refusing to
# commit or dispatch while the spec tree is off its base.

def test_a_bail_checks_every_touched_repo_back_out_onto_its_base():
    """The bail is decided after the session ended and every resume path
    checks its own branch out again — so the tree is left as the run found
    it, and a parallel session can no longer commit onto this phase
    branch."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r = ScriptedLoop(slice_dir,
                         [("code-writer", {"outcome": "blocked",
                                           "summary": "cannot proceed"})],
                         repo_root=repo)
        assert run_to_exit(r) == 3
        assert [c for root, c in r.fake_git.mutations("checkout")
                if str(root) == str(repo)][-1] == ("checkout", "main")
        assert r.fake_git.branch_at[str(repo)] == "main"
        assert "left on phase/074-P1, checked main back out" \
            in (slice_dir / "log.txt").read_text()


def test_a_bail_leaves_a_repo_with_uncommitted_work_where_it_is():
    """A checkout would carry the work across or refuse — either way it is
    someone's, so the branch stays and the log says so."""
    def leaves_work_behind(loop):
        loop.fake_git.dirty_roots[str(loop.repo_root)] = " M src/api.py\n"

    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r = ScriptedLoop(slice_dir, [(*V["exec_done"], leaves_work_behind)],
                         repo_root=repo)
        r._nudge = lambda *a, **kw: None   # the nudge commits nothing
        assert run_to_exit(r) == 3
        assert r.fake_git.branch_at[str(repo)] == "phase/074-P1"
        assert not [c for _, c in r.fake_git.mutations("checkout")
                    if c == ("checkout", "main")]
        assert "left on phase/074-P1 with uncommitted work — set aside at " \
            "resume" in (slice_dir / "log.txt").read_text()


def test_an_interrupt_leaves_the_branches_alone():
    """--resume may reattach the in-flight session, which needs the worktree
    it was interrupted on."""
    def interrupt(loop):
        raise KeyboardInterrupt

    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r = ScriptedLoop(slice_dir, [(*V["exec_done"], interrupt)],
                         repo_root=repo)
        assert run_to_exit(r) == 130
        assert r.fake_git.branch_at[str(repo)] == "phase/074-P1"
        assert not [c for _, c in r.fake_git.mutations("checkout")
                    if c == ("checkout", "main")]


def test_another_runs_phase_branch_is_never_adopted_as_a_base():
    """`_base_branch` records whatever the tree is on the first time the loop
    touches a repo. On a phase branch left by a run that bailed, that would
    cut this slice's branches from another slice's work and fast-forward into
    it."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r = ScriptedLoop(slice_dir, [], repo_root=repo)
        r.fake_git.branch_at[str(repo)] = "phase/073-P2"
        assert run_to_exit(r) == 3
        bail = json.loads((slice_dir / "bailout.json").read_text())
        assert bail["reason"] == "blocked"
        assert "phase/073-P2, a phase branch" in bail["details"]
        assert not r.spawned
        assert load_state(slice_dir)["bases"] == {}


def test_a_spec_repo_off_its_base_bails_before_the_next_dispatch():
    """An agent dispatched now would commit its plan edits and close-out
    entries onto someone else's branch. The run never moves that tree, so the
    stop names what did: a hand checkout, or an older plugin's run."""
    def moves_the_specs_checkout(loop):
        loop.fake_git.branch_at[str(loop.spec_root)] = "phase/191-P3"

    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r = ScriptedLoop(slice_dir,
                         [(*V["exec_done"], moves_the_specs_checkout)],
                         repo_root=repo)
        assert run_to_exit(r) == 3
        bail = json.loads((slice_dir / "bailout.json").read_text())
        assert bail["reason"] == "blocked"
        assert "is on phase/191-P3, not main" in bail["details"]
        assert "a hand checkout, or a run of a plugin before" \
            in bail["details"]
        assert "check out main there and resume" in bail["details"]
        # the reviewer was never dispatched onto that branch
        assert [role for role, *_ in r.spawned] == ["code-writer"]
        # and the bail did not yank that tree back either: the branch is
        # another run's, so only its owner (or the operator) moves it
        assert r.fake_git.branch_at[str(r.spec_root)] == "phase/191-P3"
        assert "which this run did not check out" \
            in (slice_dir / "log.txt").read_text()


def test_the_report_refuses_a_spec_repo_off_the_recorded_base():
    """close-out.md is committed into the shared tree at run start."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        specs = (Path(tmp) / "specs").resolve()
        state = resume_state(PROJECT)
        state["bases"] = {str(specs): "main", str(repo): "main"}
        (slice_dir / "state.json").write_text(json.dumps(state))
        r = ScriptedLoop(slice_dir, [], resume=True, repo_root=repo)
        r.fake_git.branch_at[str(specs)] = "operator-edits"
        assert run_to_exit(r) == 3
        bail = json.loads((slice_dir / "bailout.json").read_text())
        assert bail["reason"] == "blocked"
        assert "is on operator-edits, not main" in bail["details"]
        assert not r.spawned
        assert not r.fake_git.specs_ops()


def test_the_stamp_refuses_a_spec_repo_off_its_base():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        specs = (Path(tmp) / "specs").resolve()
        r = ScriptedLoop(slice_dir, [], repo_root=repo)
        r.state = {"bases": {str(specs): "main"}, "phases": {}}
        r.fake_git.branch_at[str(specs)] = "phase/191-P3"
        try:
            r._stamp_done("1")
        except Bailout as exc:
            assert exc.reason == "blocked"
            assert "check out main there and resume" in exc.details
        else:
            raise AssertionError("the stamp must not commit off the base")
        assert not r.fake_git.specs_ops()


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
        assert ('strike, `--by "consult <n>"`, what you absorbed into an appended '
                'phase (`--reason "absorbed by P<x> (<commit>)"`)') in flat
        # the verbs' shapes are the tool's, in the dispatch line — not typed
        # by hand in the situation
        assert "`strike <close-out.md>" not in flat
        assert ("close_out.py strike <close-out.md> <id> --reason REASON "
                "[--by BY]") in completion
        assert ("close_out.py note <close-out.md> <id> --by BY --text TEXT"
                in completion)
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


# DHCPApp slice 001: a code-writer filed production addresses in a public
# repo's tests as a `severe` defect proposing the fix "before the push" — and
# the report is worked after the push. The completion consult, the last
# reader before it, carries every live entry that may describe what the push
# must not carry.

B3_PROPOSAL = ("fix now, before the push: swap the 10.1.3.x addresses in "
               "test_reader.py for documentation-range ones")
GEN_BAR_OPENING = "This is the loop's first follow-up generation"


def test_completion_consult_carries_the_entries_owed_before_the_push():
    def files_b1(loop):
        run_loop.append_entry(
            loop.slice_dir, "defect", "test_reader.py carries production IPs",
            "b", consequence="the push publishes them",
            labels={"trigger": "normal-use", "impact": "severe",
                    "signal": "silent", "fix": "one-edit", "area": "plain",
                    "repo": "repo"},
            proposal=B3_PROPOSAL, due="push")
        run_loop.append_entry(loop.slice_dir, "defect", "a wrong log line", "b",
                              consequence="c",
                              labels={"trigger": "normal-use",
                                      "impact": "degraded", "signal": "silent",
                                      "fix": "one-edit", "area": "plain",
                                      "repo": "repo"})

    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        script = [(*V["exec_done"], files_b1), V["review_signoff"], *TAIL]
        r = ScriptedLoop(slice_dir, script, repo_root=repo)
        assert run_to_exit(r) == 0
        consult = next(p for role, p in r.prompts
                       if role == "consult" and "stamped done" in p)
        assert "about it.\n\nOwed before the push. The push that follows" in consult
        assert ("- B1 — test_reader.py carries production IPs (impact severe; "
                "due before the push)") in consult
        assert "B2" not in consult
        assert ("say why in a `note` on the entry and leave it.\n\n"
                + GEN_BAR_OPENING) in consult
        log = (slice_dir / "log.txt").read_text()
        assert "completion consult: 1 close-out entry owed before the push: B1" in log


def test_completion_consult_without_entries_owed_reads_as_before():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r = ScriptedLoop(slice_dir, [V["exec_done"], V["review_signoff"], *TAIL],
                         repo_root=repo)
        assert run_to_exit(r) == 0
        consult = next(p for role, p in r.prompts if role == "consult")
        assert "Owed before the push" not in consult
        # the sweep's stance, one blank line, the generation bar — no stray
        # blank line where the block would sit
        assert "about it.\n\n" + GEN_BAR_OPENING in consult
        assert "owed before the push" not in (slice_dir / "log.txt").read_text()

    # A report that cannot be read is logged; the consult goes on without it.
    def unreadable(slice_dir):
        raise run_loop.ReportError("close-out.json is not valid JSON")

    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r = ScriptedLoop(slice_dir, [V["exec_done"], V["review_signoff"], *TAIL],
                         repo_root=repo)
        with patched(run_loop, owed_before_push=unreadable):
            assert run_to_exit(r) == 0
        consult = next(p for role, p in r.prompts if role == "consult")
        assert "Owed before the push" not in consult
        assert ("close-out not read for what is owed before the push "
                "(close-out.json is not valid JSON)"
                in (slice_dir / "log.txt").read_text())


# AnsibleSpecs slice 058: a criterion worded against the plan's ruling D2 was
# reworded before the test phase only because the completion consult
# happened to read the entry — the test phase checks every criterion as
# worded, and the report is worked after it. The consult now carries every
# live entry that says a criterion of this slice is worded wrong.

V15_HEADLINE = "074 verification.json V15 is worded against ruling D2"


def files_p1(loop):
    run_loop.append_entry(
        loop.slice_dir, "prose", V15_HEADLINE, "b",
        consequence="the test phase fails a criterion the slice met",
        labels={"trigger": "normal-use", "impact": "degraded", "signal": "silent",
                "fix": "one-edit", "area": "plain", "repo": "specs"},
        proposal="reword V15 to what D2 rules", due="test")


def with_criteria(slice_dir):
    (slice_dir / "verification.json").write_text(json.dumps({"items": [
        {"id": vid, "area": "core", "description": "It ships."}
        for vid in ("V01", "V15")]}))


def test_completion_consult_carries_the_entries_to_fix_before_the_test_phase():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        with_criteria(slice_dir)
        script = [(*V["exec_done"], files_p1), V["review_signoff"], *TAIL]
        r = ScriptedLoop(slice_dir, script, repo_root=repo)
        assert run_to_exit(r) == 0
        consult = next(p for role, p in r.prompts
                       if role == "consult" and "stamped done" in p)
        assert "about it.\n\nFix before the test phase. The test phase that" in consult
        assert f"- P1 — {V15_HEADLINE} (V15)" in consult
        assert f"every criterion in {slice_dir / 'verification.json'} as it" in consult
        assert "on the entry and leave it.\n\n" + GEN_BAR_OPENING in consult
        log = (slice_dir / "log.txt").read_text()
        assert ("completion consult: 1 close-out entry to fix before the test "
                "phase: P1") in log

    # Beside an entry owed before the push: that block first, one blank line
    # between them.
    def files_both(loop):
        files_p1(loop)
        run_loop.append_entry(
            loop.slice_dir, "defect", "test_reader.py carries production IPs",
            "b", consequence="the push publishes them",
            labels={"trigger": "normal-use", "impact": "severe",
                    "signal": "silent", "fix": "one-edit", "area": "plain",
                    "repo": "repo"},
            proposal=B3_PROPOSAL, due="push")

    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        with_criteria(slice_dir)
        script = [(*V["exec_done"], files_both), V["review_signoff"], *TAIL]
        r = ScriptedLoop(slice_dir, script, repo_root=repo)
        assert run_to_exit(r) == 0
        consult = next(p for role, p in r.prompts
                       if role == "consult" and "stamped done" in p)
        assert "about it.\n\nOwed before the push. The push that follows" in consult
        assert ("say why in a `note` on the entry and leave it.\n\n"
                "Fix before the test phase. The test phase that") in consult
        assert "on the entry and leave it.\n\n" + GEN_BAR_OPENING in consult


def test_completion_consult_with_no_test_phase_leaves_the_entry_to_the_wrap_up():
    def not_read(slice_dir):
        raise AssertionError("a project with no test phase reads nothing for one")

    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp, config=rc(test=False))
        with_criteria(slice_dir)
        script = [(*V["exec_done"], files_p1), V["review_signoff"],
                  V["consult_complete"], V["doc_done"]]
        r = ScriptedLoop(slice_dir, script, repo_root=repo)
        with patched(run_loop, owed_before_test=not_read):
            assert run_to_exit(r) == 0
        consult = next(p for role, p in r.prompts if role == "consult")
        assert "Fix before the test phase" not in consult
        assert "about it.\n\n" + GEN_BAR_OPENING in consult
        assert "before the test phase" not in (slice_dir / "log.txt").read_text()


def test_completion_consult_goes_on_when_the_report_cannot_be_read_for_the_test_phase():
    def unreadable(slice_dir):
        raise run_loop.ReportError("close-out.json is not valid JSON")

    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        with_criteria(slice_dir)
        script = [(*V["exec_done"], files_p1), V["review_signoff"], *TAIL]
        r = ScriptedLoop(slice_dir, script, repo_root=repo)
        with patched(run_loop, owed_before_test=unreadable):
            assert run_to_exit(r) == 0
        consult = next(p for role, p in r.prompts if role == "consult")
        assert "Fix before the test phase" not in consult
        assert "about it.\n\n" + GEN_BAR_OPENING in consult
        assert ("close-out not read for what to fix before the test phase "
                "(close-out.json is not valid JSON)"
                in (slice_dir / "log.txt").read_text())


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
        assert "Running a promotion pipeline is operator-gated" in prompt
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
        # the bail stopped in the test stage, so the resume re-enters there;
        # the sweep record is not replayed — same heads, same report
        r2 = ScriptedLoop(slice_dir, [V["test_clean"], V["doc_done"]],
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


# -- after the consult's `complete` -------------------------------------------
#
# PilotApp slice 008: consult 2 answered `complete` with a one-line comment
# fix committed (the generation rider's residue), the driver was killed in
# the re-sweep, and the resume dispatched a third consult on the same plan —
# a full sweep first, and the same `complete` out of it. A `complete` is
# recorded before anything else runs; the residue commit is re-swept before
# the test phase (or, with none, the push and the doc phase), and only a red
# re-sweep goes to a fresh consult. None of it spends a generation.

def residue_commit(red=None):
    """A consult step's effect: it committed mechanical residue — HEAD moves
    — and, given a (component, verb), that commit turns the row red."""
    def effect(loop):
        loop.fake_git.head = "def456"
        if red is not None:
            loop.sweep_reds.add(red)
    return effect


def killed_at_sweep_call(loop, n):
    """The driver dies at its sweep command number `n` (from 0), as slice
    008's was killed from outside mid-sweep."""
    real = loop._run_sweep_cmd

    def cmd(*args, **kw):
        if len(loop.sweep_calls) == n:
            raise KeyboardInterrupt
        return real(*args, **kw)
    loop._run_sweep_cmd = cmd


def killed_in_the_resweep(slice_dir, repo):
    """A first run whose consult answers `complete` with a residue commit,
    killed in the re-sweep that commit owes (its second command)."""
    r = ScriptedLoop(slice_dir, [V["exec_done"], V["review_signoff"],
                                 (*V["consult_complete"], residue_commit())],
                     repo_root=repo)
    killed_at_sweep_call(r, 4)
    with contextlib.redirect_stderr(io.StringIO()):
        assert run_to_exit(r) == 130
    return r


def test_a_resume_after_complete_dispatches_no_consult():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        killed_in_the_resweep(slice_dir, repo)
        state = load_state(slice_dir)
        assert state["run_phase"] == "consult"
        assert state["consult_complete"] == {"consult": 1, "phases": ["1"],
                                             "sweep": 1}

        r = ScriptedLoop(slice_dir, [V["test_clean"], V["doc_done"]],
                         resume=True, repo_root=repo)
        r.fake_git.head = "def456"   # the residue commit is still there
        assert run_to_exit(r) == 0
        assert [role for role, *_ in r.spawned] == ["test-agent", "doc-writer"]
        assert len(r.sweep_calls) == 3, "the residue commit is swept, once"
        state = load_state(slice_dir)
        assert state["consult_seq"] == 1
        assert state["generation"] == 0
        assert state["gate_sweep"]["commits"] == {str(repo): "def456"}
        log = (slice_dir / "log.txt").read_text()
        assert ("the completion consult already answered `complete` (consult "
                "1) and the plan has gained nothing since — not dispatched "
                "again") in log
        assert (f"the completion consult answered `complete` with a commit in "
                f"{repo.name} — re-sweeping before the test phase") in log
        test_prompt = next(p for role, p in r.prompts if role == "test-agent")
        assert str(slice_dir / "sweeps" / "r3") in test_prompt
        assert GEN_BAR_OPENING in test_prompt


def test_a_residue_commit_swept_green_goes_on_to_the_test_phase():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        script = [V["exec_done"], V["review_signoff"],
                  (*V["consult_complete"], residue_commit()),
                  V["test_clean"], V["doc_done"]]
        r = ScriptedLoop(slice_dir, script, repo_root=repo)
        assert run_to_exit(r) == 0
        assert not r.script
        assert [role for role, *_ in r.spawned].count("consult") == 1
        assert len(r.sweep_calls) == 6
        state = load_state(slice_dir)
        assert state["sweep_runs"] == 2
        assert state["generation"] == 0
        log = (slice_dir / "log.txt").read_text()
        assert "re-sweeping before the test phase" in log
        assert ("gate sweep r2 after the consult's `complete` → GREEN — on to "
                "the test phase, no new consult") in log
        test_prompt = next(p for role, p in r.prompts if role == "test-agent")
        assert str(slice_dir / "sweeps" / "r2") in test_prompt
        assert GEN_BAR_OPENING in test_prompt

    # A `complete` that committed nothing re-sweeps nothing.
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r = ScriptedLoop(slice_dir, [V["exec_done"], V["review_signoff"],
                                     *TAIL], repo_root=repo)
        assert run_to_exit(r) == 0
        assert len(r.sweep_calls) == 3
        log = (slice_dir / "log.txt").read_text()
        assert "re-sweeping" not in log
        assert "after the consult's `complete`" not in log


def test_with_no_test_phase_a_residue_commit_is_swept_before_the_push():
    """Before this, the commit went unswept: the test phase's own re-check
    runs only where there is one, so the driver pushed it, and the doc gate
    saw it after the push in the primary repo alone."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp, config=rc(test=False))
        script = [V["exec_done"], V["review_signoff"],
                  (*V["consult_complete"], residue_commit()), V["doc_done"]]
        r = ScriptedLoop(slice_dir, script, repo_root=repo)
        assert run_to_exit(r) == 0
        assert not r.script
        assert [role for role, *_ in r.spawned][-2:] == ["consult",
                                                         "doc-writer"]
        assert len(r.sweep_calls) == 6
        state = load_state(slice_dir)
        assert state["gate_sweep"]["commits"] == {str(repo): "def456"}
        assert state["generation"] == 0
        log = (slice_dir / "log.txt").read_text()
        resweep = log.index("re-sweeping before the push and the doc phase")
        green = log.index("gate sweep r2 after the consult's `complete` → "
                          "GREEN — on to the push and the doc phase, no new "
                          "consult")
        pushed = log.index(f"pushed main in {repo}")
        assert resweep < green < pushed


def test_a_residue_commit_swept_red_goes_to_a_fresh_consult():
    """The red a loop-tail sweep always takes: a completion consult handed
    it, whose stance makes a red outstanding work — at the bar the first
    consult had, since its `complete` spent no generation."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        script = [V["exec_done"], V["review_signoff"],
                  (*V["consult_complete"],
                   residue_commit(red=(PROJECT, "lint"))),
                  V["consult_complete"],
                  V["test_clean"], V["doc_done"]]
        r = ScriptedLoop(slice_dir, script, repo_root=repo)
        assert run_to_exit(r) == 0
        assert not r.script
        consults = [p for role, p in r.prompts if role == "consult"]
        assert len(consults) == 2
        assert f"{PROJECT} lint → GREEN" in consults[0]
        assert f"{PROJECT} lint → RED" in consults[1]
        assert str(slice_dir / "sweeps" / "r2") in consults[1]
        assert "append a phase that fixes it" in consults[1].replace("\n", " ")
        assert GEN_BAR_OPENING in consults[0]
        assert GEN_BAR_OPENING in consults[1]
        state = load_state(slice_dir)
        assert state["generation"] == 0
        # the second consult committed nothing, so its `complete` over the
        # red it was handed goes on to a test phase handed the same red
        assert state["sweep_runs"] == 2
        assert state["consult_complete"] == {"consult": 2, "phases": ["1"],
                                             "sweep": 2}
        test_prompt = next(p for role, p in r.prompts if role == "test-agent")
        assert "does not leave the machine" in test_prompt.replace("\n", " ")
        log = (slice_dir / "log.txt").read_text()
        assert ("gate sweep r2 after the consult's `complete` → RED — a fresh "
                "completion consult is handed it; no generation spent") in log

    # A fresh consult that appends the fix spends the generation it always
    # would — the first.
    def fixes_lint(loop):
        loop.fake_git.head = "fed789"
        loop.sweep_reds.clear()

    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        script = [V["exec_done"], V["review_signoff"],
                  (*V["consult_complete"],
                   residue_commit(red=(PROJECT, "lint"))),
                  ("consult", {"outcome": "appended", "summary": "lint red"},
                   append_phase("2", "Fix the lint")),
                  (*V["exec_done"], fixes_lint), V["review_signoff"],
                  *TAIL]
        r = ScriptedLoop(slice_dir, script, repo_root=repo)
        assert run_to_exit(r) == 0
        assert not r.script
        state = load_state(slice_dir)
        assert state["generation"] == 1
        consults = [p for role, p in r.prompts if role == "consult"]
        assert GEN_BAR_OPENING in consults[1]
        assert "BLOCKING work only" in consults[2]


def test_a_state_from_before_the_record_dispatches_the_consult_again():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        killed_in_the_resweep(slice_dir, repo)
        state = load_state(slice_dir)
        del state["consult_complete"]
        (slice_dir / "state.json").write_text(json.dumps(state))

        r = ScriptedLoop(slice_dir, [V["consult_complete"], V["test_clean"],
                                     V["doc_done"]],
                         resume=True, repo_root=repo)
        r.fake_git.head = "def456"
        assert run_to_exit(r) == 0
        assert [role for role, *_ in r.spawned] == ["consult", "test-agent",
                                                    "doc-writer"]
        assert len(r.sweep_calls) == 3, "the consult's sweep, reused after it"
        assert load_state(slice_dir)["generation"] == 0
        assert "already answered" not in (slice_dir / "log.txt").read_text()


def test_a_phase_appended_after_complete_drops_the_record():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r1 = killed_in_the_resweep(slice_dir, repo)
        append_phase("2", "The operator's own")(r1)

        r = ScriptedLoop(slice_dir, [V["exec_done"], V["review_signoff"],
                                     *TAIL], resume=True, repo_root=repo)
        r.fake_git.head = "def456"
        assert run_to_exit(r) == 0
        assert [role for role, *_ in r.spawned] == [
            "code-writer", "code-reviewer", "consult", "test-agent",
            "doc-writer"]
        state = load_state(slice_dir)
        assert state["consult_complete"]["consult"] == 2
        assert state["consult_complete"]["phases"] == ["1", "2"]
        assert state["generation"] == 0
        assert "already answered" not in (slice_dir / "log.txt").read_text()


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


def test_a_sweep_row_that_ran_nothing_is_neither_green_nor_red():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r = KcExitLoop(slice_dir, [V["exec_done"], V["review_signoff"],
                                   *TAIL],
                       repo_root=repo, sweep_rcs={(PROJECT, "lint"): 3})
        assert run_to_exit(r) == 0
        state = load_state(slice_dir)
        sweep = state["gate_sweep"]
        assert sweep["outcome"] == "green" and sweep["green"] is True
        assert {row["verb"]: (row["outcome"], row["green"])
                for row in sweep["results"]} == {
            "lint": ("nothing_ran", False), "build": ("green", True),
            "test": ("green", True)}
        row = next(h for h in state["history"] if h["role"] == "sweep")
        assert row["outcome"] == "green"
        assert row["summary"] == "3 command(s), 1 of them ran nothing"
        for role in ("consult", "test-agent"):
            prompt = next(p for rl, p in r.prompts if rl == role)
            assert f"{PROJECT} lint → nothing ran — " in prompt
            assert f"{PROJECT} test → GREEN — " in prompt
            flat = prompt.replace("\n", " ")
            assert "Every row that ran is GREEN" in flat
            assert "A `nothing ran` row found nothing to run" in flat


def test_a_sweep_in_which_nothing_ran_reads_as_unverified():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r = KcExitLoop(slice_dir, [V["exec_done"], V["review_signoff"],
                                   *TAIL],
                       repo_root=repo,
                       sweep_rcs={(PROJECT, verb): 3
                                  for verb in run_loop.SWEEP_VERBS})
        assert run_to_exit(r) == 0
        sweep = load_state(slice_dir)["gate_sweep"]
        assert sweep["outcome"] == "nothing_ran" and sweep["green"] is False
        consult = next(p for role, p in r.prompts if role == "consult")
        assert f"{PROJECT} build → nothing ran" in consult
        assert run_loop.SWEEP_STANCE_NONE in consult
        assert "GREEN" not in consult and "RED row" not in consult


def test_a_red_row_beside_one_that_ran_nothing_is_a_red_sweep():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r = KcExitLoop(slice_dir, [V["exec_done"], V["review_signoff"],
                                   *TAIL],
                       repo_root=repo, sweep_rcs={(PROJECT, "lint"): 3,
                                                  (PROJECT, "test"): 1})
        assert run_to_exit(r) == 0
        assert load_state(slice_dir)["gate_sweep"]["outcome"] == "red"
        consult = next(p for role, p in r.prompts if role == "consult")
        assert f"{PROJECT} test → RED" in consult
        assert "append a phase that fixes it" in consult.replace("\n", " ")


def test_a_sweep_recorded_before_rows_had_an_outcome_still_renders():
    """A resume reuses the recorded sweep while the heads match — one an
    older plugin wrote carries `green` alone."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r = ScriptedLoop(slice_dir, [], repo_root=repo)
        old = {"commits": {str(repo): "abc123"}, "green": False,
               "results": [{"repo": str(repo), "component": PROJECT,
                            "verb": "test", "green": False, "log": "t.log"}]}
        block = r._sweep_block(old, "GREEN-STANCE", "RED-STANCE")
        assert f"{PROJECT} test → RED — t.log" in block
        assert block.endswith("RED-STANCE")


# -- a sweep test row keeps its suite's files; a red one re-runs (AIWF-94) -----
#
# The sweep kept kc's lines alone. A ModernAppTemplate repo's frontend suite
# overwrote the backend's test_results.md at the repo root; the consult's own
# re-run deleted Playwright's test-results/ minutes after; and nothing said
# whether a red reproduced — a flake got a phase appended, and another
# "flake" was a real bug. Every test row now keeps the files its run wrote,
# and a red one re-runs once, whole, and stays red either way.

LONG_AGO = 1_600_000_000   # an mtime from 2020: a file no run here wrote


class SweepRunLoop(KcExitLoop):
    """KcExitLoop whose sweep commands are scripted per (component, verb)
    as a list of steps, one per run in order (exit 0 once spent): an exit
    code, TIMED_OUT, or a callable standing in for the suite — it does on
    disk what the suite would and returns the exit code."""

    def __init__(self, slice_dir, script, sweep_steps=None, **kw):
        super().__init__(slice_dir, script, **kw)
        self.sweep_steps = {k: list(v) for k, v in (sweep_steps or {}).items()}
        self.sweep_argvs = []

    def _gate_exec(self, argv, cwd, log_file):
        if not self._sweeping:
            return super()._gate_exec(argv, cwd, log_file)
        steps = self.sweep_steps.get((argv[4], argv[2]), [])
        step = steps.pop(0) if steps else 0
        self.sweep_argvs.append(list(argv))
        if step is TIMED_OUT:
            raise subprocess.TimeoutExpired(argv, run_loop.GATE_TIMEOUT)
        rc_ = step() if callable(step) else step
        log_file.write(f"{' '.join(argv)}: exit {rc_}\n")
        return rc_


def suite_writes(rc_, files, mtime=None):
    """A sweep step: the suite writes `files` ({path: text or bytes}) and
    exits `rc_`; `mtime` back-dates what it wrote."""
    def step():
        for path, content in files.items():
            path = Path(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(content, bytes):
                path.write_bytes(content)
            else:
                path.write_text(content)
            if mtime is not None:
                os.utime(path, (mtime, mtime))
        return rc_
    return step


def run_sweep(loop, repo, components=None):
    """One gate sweep over `repo`, outside a run, with `components` as `kc
    project list` gives them (the suite's one component at the repo root
    by default): the sweep record and what it announced."""
    loop.state.setdefault("history", [])
    out = io.StringIO()
    listed = components or {PROJECT: Path(repo)}
    with patched(run_loop, load_project_dirs=lambda cwd: dict(listed)), \
            contextlib.redirect_stdout(out):
        sweep = loop._run_gate_sweep([repo], {str(repo): "abc123def4567"})
    return sweep, out.getvalue()


def sweep_row(sweep, component, verb="test"):
    return next(row for row in sweep["results"]
                if row["component"] == component and row["verb"] == verb)


def test_a_red_sweep_test_row_that_passes_its_rerun_is_red_and_flaky():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r = SweepRunLoop(slice_dir, [V["exec_done"], V["review_signoff"],
                                     *TAIL], repo_root=repo,
                         sweep_steps={(PROJECT, "test"): [1, 0]})
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            assert run_to_exit(r) == 0
        test_argv = ["kc", "project", "test", "--project", PROJECT]
        # the whole component, the same command, once more — and only once
        assert r.sweep_argvs.count(test_argv) == 2
        state = load_state(slice_dir)
        sweep = state["gate_sweep"]
        assert sweep["outcome"] == "red" and sweep["green"] is False
        row = sweep_row(sweep, PROJECT)
        assert row["outcome"] == "red" and row["green"] is False
        rerun = row["rerun"]
        assert rerun["outcome"] == "green"
        out_dir = slice_dir / "sweeps" / "r1"
        assert rerun["log"] == str(out_dir / f"repo_{PROJECT}_test_rerun.log")
        assert Path(rerun["log"]).is_file()
        assert isinstance(rerun["duration_s"], int)
        assert rerun["artifacts"] == [] and row["artifacts"] == []
        summary = next(h for h in state["history"]
                       if h["role"] == "sweep")["summary"]
        assert summary == f"repo/{PROJECT} test (flaky)"
        assert f"gate sweep r1 → RED (repo/{PROJECT} test (flaky))" \
            in out.getvalue()
        for role in ("consult", "test-agent"):
            prompt = next(p for rl, p in r.prompts if rl == role)
            assert (f"  - {PROJECT} test → RED (flaky: passed on re-run) — "
                    f"{row['log']}\n    - re-run: {rerun['log']}") in prompt
            flat = prompt.replace("\n", " ")
            assert "A flaky row is still RED and yours to judge" in flat
            assert "`test_results.md`, Playwright's `test-results/`" in flat
        assert "append a phase that fixes it" in next(
            p for rl, p in r.prompts if rl == "consult").replace("\n", " ")
        assert "test → RED (flaky: passed on re-run) after its re-run" \
            in (slice_dir / "log.txt").read_text()


def test_a_red_sweep_test_row_that_fails_its_rerun_is_reproduced():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r = SweepRunLoop(slice_dir, [], repo_root=repo,
                         sweep_steps={(PROJECT, "test"): [1, 1]})
        sweep, out = run_sweep(r, repo)
        row = sweep_row(sweep, PROJECT)
        assert row["outcome"] == "red" and row["rerun"]["outcome"] == "red"
        assert f"gate sweep r1 → RED (repo/{PROJECT} test (reproduced))" in out
        block = r._sweep_block(sweep, "GREEN-STANCE", "RED-STANCE")
        assert f"{PROJECT} test → RED (reproduced) — " in block
        assert "A flaky row is still RED" in block.replace("\n", " ")


def test_a_sweep_rerun_that_times_out_is_recorded_not_bailed():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r = SweepRunLoop(slice_dir, [], repo_root=repo,
                         sweep_steps={(PROJECT, "test"): [1, TIMED_OUT]})
        sweep, out = run_sweep(r, repo)
        row = sweep_row(sweep, PROJECT)
        assert row["outcome"] == "red" and row["green"] is False
        assert row["rerun"]["outcome"] == "timeout"
        assert sweep["outcome"] == "red"
        assert f"repo/{PROJECT} test (re-run timed out)" in out
        block = r._sweep_block(sweep, "GREEN-STANCE", "RED-STANCE")
        assert f"{PROJECT} test → RED (re-run timed out) — " in block
    # the first run's timeout still bails, as before
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r = SweepRunLoop(slice_dir, [], repo_root=repo,
                         sweep_steps={(PROJECT, "test"): [TIMED_OUT]})
        try:
            run_sweep(r, repo)
        except Bailout as e:
            assert e.reason == "timeout"
        else:
            raise AssertionError("a first run that timed out did not bail")
    # and a re-run kc refuses as a usage error is the driver bug it always is
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r = SweepRunLoop(slice_dir, [], repo_root=repo,
                         sweep_steps={(PROJECT, "test"): [1, 2]})
        try:
            run_sweep(r, repo)
        except Bailout as e:
            assert e.reason == "protocol_failure"
            assert "test_rerun.log" in e.details
        else:
            raise AssertionError("a re-run's rc 2 did not bail")


def test_each_test_row_keeps_the_test_results_md_its_own_run_wrote():
    """ModernAppTemplate: backend and frontend both write the repo root's
    test_results.md, so each is copied before the next suite runs; a
    component whose suite writes none is never handed another's."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        root_md = repo / run_loop.TEST_RESULTS_NAME
        stale = repo / "worker" / run_loop.TEST_RESULTS_NAME
        stale.parent.mkdir()
        stale.write_text("worker: from some earlier run")
        os.utime(stale, (LONG_AGO, LONG_AGO))
        components = {"backend": repo / "backend",
                      "frontend": repo / "frontend",
                      "worker": repo / "worker"}
        r = SweepRunLoop(slice_dir, [], repo_root=repo, sweep_steps={
            ("backend", "test"): [
                suite_writes(1, {root_md: "backend: test_login failed"}),
                suite_writes(1, {root_md: "backend: test_login failed again"})],
            ("frontend", "test"): [
                suite_writes(0, {root_md: "frontend: all passed"})],
        })
        sweep, _ = run_sweep(r, repo, components)
        out_dir = slice_dir / "sweeps" / "r1"
        backend = sweep_row(sweep, "backend")
        kept = out_dir / "repo_backend_test_results.md"
        kept_rerun = out_dir / "repo_backend_test_results_rerun.md"
        assert backend["artifacts"] == [str(kept)]
        assert kept.read_text() == "backend: test_login failed"
        assert backend["rerun"]["artifacts"] == [str(kept_rerun)]
        assert kept_rerun.read_text() == "backend: test_login failed again"
        # a green row keeps its own too
        frontend = sweep_row(sweep, "frontend")
        assert frontend["artifacts"] == [
            str(out_dir / "repo_frontend_test_results.md")]
        assert (out_dir / "repo_frontend_test_results.md").read_text() \
            == "frontend: all passed"
        # the worker's suite wrote nothing: neither its own stale file nor
        # the frontend's, a moment old at the root, is its
        assert sweep_row(sweep, "worker")["artifacts"] == []
        assert not (out_dir / "repo_worker_test_results.md").exists()
        # the dispatch lists a red row's copies, never a green row's
        block = r._sweep_block(sweep, "GREEN-STANCE", "RED-STANCE")
        assert f"    - copied: {kept}, {kept_rerun}" in block
        assert "repo_frontend_test_results.md" not in block


def test_the_component_directory_is_looked_in_before_the_repo_root():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        name = run_loop.TEST_RESULTS_NAME
        components = {"docs": repo / "docs", "legacy": repo / "legacy"}
        r = SweepRunLoop(slice_dir, [], repo_root=repo, sweep_steps={
            ("docs", "test"): [suite_writes(0, {
                repo / "docs" / name: "docs: its own",
                repo / name: "docs: at the root"})],
            # written by the run, but back-dated: older than its start
            ("legacy", "test"): [suite_writes(
                0, {repo / "legacy" / name: "legacy: back-dated"},
                mtime=LONG_AGO)],
        })
        sweep, _ = run_sweep(r, repo, components)
        out_dir = slice_dir / "sweeps" / "r1"
        assert (out_dir / "repo_docs_test_results.md").read_text() \
            == "docs: its own"
        assert sweep_row(sweep, "legacy")["artifacts"] == []


def test_a_red_test_row_keeps_its_test_results_dir_within_the_cap():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        results = repo / "frontend" / run_loop.TEST_RESULTS_DIR
        old = results / "old-run" / "trace.zip"
        old.parent.mkdir(parents=True)
        old.write_bytes(b"t" * 20)
        os.utime(old, (LONG_AGO, LONG_AGO))
        spec = results / "login-spec-chromium"
        r = SweepRunLoop(slice_dir, [], repo_root=repo, sweep_steps={
            ("frontend", "test"): [
                suite_writes(1, {spec / "error-context.md": "x" * 10,
                                 spec / "test-failed-1.png": b"p" * 50,
                                 spec / "video.webm": b"v" * 500}),
                suite_writes(1, {spec / "error-context.md": "again"})],
        })
        with patched(run_loop, TEST_RESULTS_DIR_CAP=100):
            sweep, _ = run_sweep(r, repo, {"frontend": repo / "frontend"})
        out_dir = slice_dir / "sweeps" / "r1"
        row = sweep_row(sweep, "frontend")
        kept = out_dir / "repo_frontend_test-results"
        assert row["artifacts"] == [str(kept)]
        copied = kept / "login-spec-chromium"
        assert (copied / "error-context.md").read_text() == "x" * 10
        assert (copied / "test-failed-1.png").is_file()
        # the cap: the smallest first, the video left out and logged
        assert not (copied / "video.webm").exists()
        log = (slice_dir / "log.txt").read_text()
        assert f"{results} is over the" in log and "MB cap" in log
        assert "2 file(s) copied, smallest first; 1 (0.0 MB) left out" in log
        # a file no run here wrote is not this one's
        assert not (kept / "old-run").exists()
        # still red on its re-run: that run's own files, in a folder of its own
        kept_rerun = out_dir / "repo_frontend_test-results_rerun"
        assert row["rerun"]["artifacts"] == [str(kept_rerun)]
        assert sorted(p.name for p in kept_rerun.rglob("*") if p.is_file()) \
            == [".gitignore", "error-context.md"]
        assert (kept_rerun / "login-spec-chromium"
                / "error-context.md").read_text() == "again"


def test_a_kept_test_results_dir_ignores_itself_in_the_spec_repo():
    """The slice folder's sweep logs are committed with it; the copied
    test-results/ are evidence for this run, not record — and may hold
    videos and traces. The test_results.md copies, small text, stay."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        specs = Path(tmp) / "specs"
        shutil.rmtree(specs / ".git")
        sh(specs, "init", "-q", "-b", "main")
        spec = repo / "frontend" / run_loop.TEST_RESULTS_DIR / "a-spec"
        md = repo / run_loop.TEST_RESULTS_NAME
        r = SweepRunLoop(slice_dir, [], repo_root=repo, sweep_steps={
            ("frontend", "test"): [
                suite_writes(1, {spec / "error-context.md": "failed",
                                 spec / ".gitignore": "!*\n", md: "1 failed"}),
                suite_writes(1, {spec / "error-context.md": "failed again",
                                 md: "1 failed again"})],
        })
        sweep, _ = run_sweep(r, repo, {"frontend": repo / "frontend"})
        out_dir = slice_dir / "sweeps" / "r1"
        for name in ("repo_frontend_test-results",
                     "repo_frontend_test-results_rerun"):
            assert (out_dir / name / ".gitignore").read_text() == "*\n"
        status = sh(specs, "status", "--porcelain", "--untracked-files=all")
        assert "test-results" not in status
        assert "sweeps/r1/repo_frontend_test_results.md" in status
        assert "sweeps/r1/repo_frontend_test_results_rerun.md" in status
        assert "sweeps/r1/repo_frontend_test.log" in status


def test_a_test_rerun_that_passes_keeps_no_test_results_dir():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        spec = repo / "frontend" / run_loop.TEST_RESULTS_DIR / "a-spec"
        r = SweepRunLoop(slice_dir, [], repo_root=repo, sweep_steps={
            ("frontend", "test"): [
                suite_writes(1, {spec / "error-context.md": "failed"}),
                suite_writes(0, {spec / "trace.zip": b"passed"})],
        })
        sweep, _ = run_sweep(r, repo, {"frontend": repo / "frontend"})
        row = sweep_row(sweep, "frontend")
        assert row["rerun"]["outcome"] == "green"
        assert row["rerun"]["artifacts"] == []
        out_dir = slice_dir / "sweeps" / "r1"
        assert not (out_dir / "repo_frontend_test-results_rerun").exists()


def test_a_red_test_row_without_a_test_results_dir_is_no_error():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        (repo / "frontend" / run_loop.TEST_RESULTS_DIR).mkdir(parents=True)
        r = SweepRunLoop(slice_dir, [], repo_root=repo, sweep_steps={
            ("frontend", "test"): [1, 1], ("backend", "test"): [1, 1]})
        sweep, _ = run_sweep(r, repo, {"frontend": repo / "frontend",
                                       "backend": repo / "backend"})
        for component in ("frontend", "backend"):   # empty, then missing
            row = sweep_row(sweep, component)
            assert row["artifacts"] == [] and row["rerun"]["artifacts"] == []
        assert not list((slice_dir / "sweeps" / "r1").glob("*test-results*"))


def test_a_green_test_row_does_not_rerun_or_keep_its_test_results_dir():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        spec = repo / "frontend" / run_loop.TEST_RESULTS_DIR / "a-spec"
        r = SweepRunLoop(slice_dir, [], repo_root=repo, sweep_steps={
            ("frontend", "test"): [
                suite_writes(0, {spec / "trace.zip": b"t",
                                 repo / run_loop.TEST_RESULTS_NAME: "ok"})]})
        sweep, _ = run_sweep(r, repo, {"frontend": repo / "frontend"})
        assert r.sweep_argvs.count(
            ["kc", "project", "test", "--project", "frontend"]) == 1
        row = sweep_row(sweep, "frontend")
        assert row["outcome"] == "green" and "rerun" not in row
        out_dir = slice_dir / "sweeps" / "r1"
        assert row["artifacts"] == [str(out_dir
                                        / "repo_frontend_test_results.md")]
        assert not (out_dir / "repo_frontend_test-results").exists()


def test_lint_and_build_rows_never_rerun_or_keep_files():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        spec = repo / run_loop.TEST_RESULTS_DIR / "a-spec"
        md = repo / run_loop.TEST_RESULTS_NAME
        r = SweepRunLoop(slice_dir, [], repo_root=repo, sweep_steps={
            (PROJECT, "lint"): [suite_writes(1, {md: "lint", spec / "l": "l"})],
            (PROJECT, "build"): [suite_writes(1, {md: "b", spec / "b": "b"})]})
        sweep, out = run_sweep(r, repo)
        for verb in ("lint", "build"):
            assert r.sweep_argvs.count(
                ["kc", "project", verb, "--project", PROJECT]) == 1
            row = sweep_row(sweep, PROJECT, verb)
            assert row["outcome"] == "red"
            assert "rerun" not in row and "artifacts" not in row
        assert not list((slice_dir / "sweeps" / "r1").glob("*test_results*"))
        assert not list((slice_dir / "sweeps" / "r1").glob("*test-results*"))
        assert f"RED (repo/{PROJECT} lint, repo/{PROJECT} build)" in out
        block = r._sweep_block(sweep, "GREEN-STANCE", "RED-STANCE")
        assert f"{PROJECT} lint → RED — " in block
        assert "re-run" not in block and "copied:" not in block


def test_a_red_row_an_accept_ruling_covers_reruns_and_carries_its_mark():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        ruled_plan(slice_dir, "accept app test — flaky before this slice, "
                              "ANS-7")
        r = SweepRunLoop(slice_dir, [V["exec_done"], V["review_signoff"],
                                     *TAIL], repo_root=repo,
                         sweep_steps={(PROJECT, "test"): [1, 0]})
        assert run_to_exit(r) == 0
        row = sweep_row(load_state(slice_dir)["gate_sweep"], PROJECT)
        assert row["rerun"]["outcome"] == "green"
        consult = next(p for rl, p in r.prompts if rl == "consult")
        assert (f"{PROJECT} test → RED (flaky: passed on re-run), accepted "
                "by ruling (flaky before this slice, ANS-7) — ") in consult
        # accepted is not red: no copies listed, no note about them
        assert "re-run:" not in consult
        assert "A flaky row is still RED" not in consult.replace("\n", " ")


def test_sweep_rows_recorded_before_reruns_still_render():
    """A resume reuses a sweep an older plugin recorded while the heads
    match: its red rows carry no `rerun` and no `artifacts`."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r = SweepRunLoop(slice_dir, [], repo_root=repo)
        old = {"commits": {str(repo): "abc123def4567"}, "outcome": "red",
               "green": False,
               "results": [{"repo": str(repo), "component": PROJECT,
                            "verb": verb, "outcome": "red", "green": False,
                            "log": f"{verb}.log", "duration_s": 3}
                           for verb in ("build", "test")]}
        block = r._sweep_block(old, "GREEN-STANCE", "RED-STANCE")
        assert f"  - {PROJECT} build → RED — build.log\n" in block
        assert f"  - {PROJECT} test → RED — test.log\n" in block
        assert "    - " not in block
        assert block.endswith("RED-STANCE")
        assert r._red_name(old["results"][1]) == f"repo/{PROJECT} test"
        assert run_loop.rerun_mark(old["results"][1]) is None
        # beside a row recorded with its re-run, each renders as it was kept
        new = {**old["results"][1], "log": "new.log",
               "rerun": {"outcome": "red", "log": "rerun.log",
                         "duration_s": 3, "artifacts": []},
               "artifacts": ["kept.md"]}
        block = r._sweep_block({**old, "results": [old["results"][1], new]},
                               "GREEN-STANCE", "RED-STANCE")
        assert f"  - {PROJECT} test → RED — test.log\n  - {PROJECT} test" \
            in block
        assert (f"  - {PROJECT} test → RED (reproduced) — new.log\n"
                "    - re-run: rerun.log\n    - copied: kept.md") in block
        assert "A flaky row is still RED" in block.replace("\n", " ")


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


def test_doc_gate_goes_on_past_a_verb_that_ran_nothing():
    """A repo whose components define no lint statement is not red — a nudge
    would hand the writer a failure it cannot fix."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        loop = RunLoop(slice_dir, resume=False)
        loop.repo_root = repo
        loop.state = {"history": []}
        calls = []
        rcs = {"lint": 3}
        loop._doc_gate_exec = lambda argv, log_file: calls.append(
            argv[2]) or rcs.get(argv[2], 0)
        ds = {"gate_runs": 0}
        passed, log_path = loop._run_doc_gate(ds)
        assert passed and calls == ["lint", "build", "test"]
        assert "nothing ran: no component defines a lint statement" \
            in log_path.read_text()
        assert loop.state["history"][-1]["outcome"] == "green"
        rcs.update(build=3, test=3)
        passed, _ = loop._run_doc_gate(ds)
        assert passed
        assert loop.state["history"][-1]["outcome"] == "nothing_ran"
        rcs.update(test=1)
        passed, _ = loop._run_doc_gate(ds)
        assert not passed
        assert loop.state["history"][-1]["outcome"] == "red"


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


# -- the base sync: a phase is cut from what origin holds ---------------------
#
# Ansible slice 049's P10 was cut from a `main` ten commits behind origin,
# where another slice had edited the same anchors, and its push needed a
# hand merge. A fresh phase's base with no commits of its own is
# fast-forwarded before the cut; where origin still holds commits the base
# lacks, every code-writer dispatch of the phase says so. Real git, with a
# real origin.

class FetchingLoop(RealGitLoop):
    """RealGitLoop that fetches every repo with an origin, as the driver
    does."""

    def _fetch_origin(self, root):
        if sh(root, "remote"):
            RunLoop._fetch_origin(self, root)


def with_origin(tmp, repo):
    """A bare origin for `repo`, its main pushed there, and another clone of
    it — another environment's — to push from."""
    bare = Path(tmp) / f"{repo.name}-origin.git"
    sh(tmp, "init", "-q", "--bare", "-b", "main", str(bare))
    sh(repo, "remote", "add", "origin", str(bare))
    sh(repo, "push", "-q", "-u", "origin", "main")
    other = Path(tmp) / f"{repo.name}-elsewhere"
    sh(tmp, "clone", "-q", str(bare), str(other))
    return other


def pushed(clone, path, text):
    """A commit of `path` in `clone`, pushed to origin; its sha."""
    file = clone / path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(text)
    sh(clone, "add", path)
    sh(clone, "commit", "-qm", f"elsewhere: {path}")
    sh(clone, "push", "-q", "origin", "main")
    return sh(clone, "rev-parse", "HEAD")


def real_code_slice(tmp):
    """A slice whose one phase works on the code repo in place and names
    `docs/runbook.md`, over real git: the specs and the code repo committed
    on main, the code repo with an origin and another clone of it (the
    third value). A run ends at its completion consult."""
    slice_dir, repo = make_slice(
        tmp, phases=[("1", "Runbook", PROJECT, False,
                      "Rewrite the restart section of `docs/runbook.md`.\n")],
        config=rc(test=False, doc=False, push=False))
    specs = (Path(tmp) / "specs").resolve()
    shutil.rmtree(specs / ".git")
    (repo / "docs").mkdir()
    (repo / "docs" / "runbook.md").write_text("restart: by hand\n")
    for where in (specs, repo):
        sh(where, "init", "-q", "-b", "main")
        sh(where, "add", "-A")
        sh(where, "commit", "-qm", "init")
    return slice_dir, repo, with_origin(tmp, repo)


def local_commit(repo, path):
    """A commit on the code repo's main that origin has not got; its sha."""
    file = repo / path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text("local\n")
    sh(repo, "add", path)
    sh(repo, "commit", "-qm", f"local: {path}")
    return sh(repo, "rev-parse", "HEAD")


def cuts_and_commits(seen):
    """A script step's effect: the writer notes the commit its branch was
    cut from, then commits its work on the branch."""
    def effect(loop):
        repo = loop.repo_root
        seen["cut_from"] = sh(repo, "rev-parse", "HEAD")
        (repo / "src").mkdir(exist_ok=True)
        (repo / "src" / "work.py").write_text("the phase's\n")
        sh(repo, "add", "-A")
        sh(repo, "commit", "-qm", "P1: the work")
    return effect


def flat(text):
    return " ".join(text.split())


AHEAD_WORDS = "commit(s) ahead of the local"


def test_a_base_behind_origin_is_fast_forwarded_before_the_phase_is_cut():
    if shutil.which("git") is None:
        return
    with tempfile.TemporaryDirectory() as tmp, plain_git():
        slice_dir, repo, other = real_code_slice(tmp)
        pushed(other, "docs/runbook.md", "restart: the script\n")
        tip = pushed(other, "src/other.py", "other\n")
        seen = {}
        r = FetchingLoop(slice_dir, [(*V["exec_done"], cuts_and_commits(seen)),
                                     V["review_signoff"],
                                     V["consult_complete"]], repo_root=repo)
        assert run_to_exit(r) == 0
        assert seen["cut_from"] == tip
        assert sh(repo, "rev-parse", "main~1") == tip
        assert "[P1] main fast-forwarded 2 commit(s) to origin/main in repo" \
            in (slice_dir / "log.txt").read_text()
        writers = [p for role, p in r.prompts if role == "code-writer"]
        assert writers and not any(AHEAD_WORDS in p for p in writers)


def test_a_base_ahead_of_origin_is_left_and_no_dispatch_says_a_word():
    if shutil.which("git") is None:
        return
    with tempfile.TemporaryDirectory() as tmp, plain_git():
        slice_dir, repo, _ = real_code_slice(tmp)
        local = local_commit(repo, "src/local.py")
        origin = sh(repo, "rev-parse", "origin/main")
        seen = {}
        r = FetchingLoop(slice_dir, [(*V["exec_done"], cuts_and_commits(seen)),
                                     V["review_signoff"],
                                     V["consult_complete"]], repo_root=repo)
        assert run_to_exit(r) == 0
        assert seen["cut_from"] == local
        assert sh(repo, "rev-parse", "origin/main") == origin
        log = (slice_dir / "log.txt").read_text()
        for words in ("fast-forwarded", "diverged", "behind origin"):
            assert words not in log
        assert not any(AHEAD_WORDS in p for _, p in r.prompts)


def test_diverged_bases_are_never_moved_and_every_writer_dispatch_says_so():
    """One local commit, two on origin — one of them touching the path the
    phase names. The base stays; the first round and the gate's fix round
    are told, with only the named path; the reviewer and the consult are
    not."""
    if shutil.which("git") is None:
        return
    with tempfile.TemporaryDirectory() as tmp, plain_git():
        slice_dir, repo, other = real_code_slice(tmp)
        local = local_commit(repo, "src/local.py")
        pushed(other, "docs/runbook.md", "restart: the script\n")
        pushed(other, "src/other.py", "other\n")
        seen = {}
        script = [(*V["exec_done"], cuts_and_commits(seen)), V["exec_done"],
                  V["review_signoff"], V["consult_complete"]]
        r = FetchingLoop(slice_dir, script, gates=[False, True],
                         repo_root=repo)
        assert run_to_exit(r) == 0
        assert seen["cut_from"] == local
        assert sh(repo, "rev-list", "--count", "main..origin/main") == "2"
        assert ("[P1] main and origin/main have diverged in repo (1 commit(s) "
                "local, 2 on origin) — not moved") \
            in (slice_dir / "log.txt").read_text()
        line = ("origin/main is 2 commit(s) ahead of the local main this "
                "phase's branch was cut from, which has 1 commit(s) of its "
                "own origin lacks; they touch `docs/runbook.md`, which this "
                "phase names. The driver has neither merged nor rebased.")
        writers = [p for role, p in r.prompts if role == "code-writer"]
        assert len(writers) == 2
        for prompt in writers:
            assert line in flat(prompt)
            assert "src/other.py" not in prompt
        others = [role for role, p in r.prompts if role != "code-writer"]
        assert others == ["code-reviewer", "consult"]
        assert not any(AHEAD_WORDS in p for role, p in r.prompts
                       if role != "code-writer")


def shared_slice_behind_origin(tmp):
    """`real_shared_slice` with a phase that names api.md and the close-out
    report the plan loop leaves committed (so the run commits nothing on the
    base before the phase), pushed to an origin that then took one more
    commit of api.md's line 10 from elsewhere; that commit is the fourth
    value."""
    slice_dir, repo, specs = real_shared_slice(
        tmp, body="Settle the contract in `api.md`.\n")
    run_loop.init_report(slice_dir)
    sh(specs, "add", "-A")
    sh(specs, "commit", "-qm", "slice 074: close-out report")
    other = with_origin(tmp, specs)
    edit_line(other / "api.md", 10, "line 10, origin's")
    sh(other, "commit", "-qam", "elsewhere: api.md")
    sh(other, "push", "-q", "origin", "main")
    return slice_dir, repo, specs, sh(other, "rev-parse", "HEAD")


def test_a_shared_checkout_behind_origin_is_fast_forwarded_before_the_cut():
    if shutil.which("git") is None:
        return
    with tempfile.TemporaryDirectory() as tmp, plain_git():
        slice_dir, repo, specs, tip = shared_slice_behind_origin(tmp)
        seen = {}

        def looks(loop):
            work = Path(loop.state["phases"]["1"]["worktree"])
            seen["cut_from"] = sh(work, "rev-parse", "HEAD~1")

        r, code = shared_run(slice_dir, repo, specs, looks, loop=FetchingLoop)
        assert code == 0
        assert seen["cut_from"] == tip
        assert "[P1] main fast-forwarded 1 commit(s) to origin/main in specs" \
            in (slice_dir / "log.txt").read_text()
        text = (specs / "api.md").read_text()
        assert "line 1, the phase's" in text and "line 10, origin's" in text
        assert not any(AHEAD_WORDS in p for _, p in r.prompts)


def test_a_dirty_file_in_the_way_leaves_a_shared_base_behind_and_the_run_goes_on():
    """The shared checkout's `merge --ff-only` refuses over another writer's
    uncommitted edit in a file origin's commit touches: a log line, never a
    bail — the worktree is cut from the base as it stands, and the writer is
    told."""
    if shutil.which("git") is None:
        return
    with tempfile.TemporaryDirectory() as tmp, plain_git():
        slice_dir, repo, specs, _ = shared_slice_behind_origin(tmp)
        edit_line(specs / "api.md", 5, "line 5, left uncommitted")
        before = sh(specs, "rev-parse", "main")
        seen = {}

        def looks(loop):
            work = Path(loop.state["phases"]["1"]["worktree"])
            seen["cut_from"] = sh(work, "rev-parse", "HEAD~1")

        r, code = shared_run(slice_dir, repo, specs, looks, loop=FetchingLoop)
        assert code == 0
        assert seen["cut_from"] == before
        assert ("[P1] main left 1 commit(s) behind origin/main in specs: "
                "error: Your local changes to the following files would be "
                "overwritten by merge:") in (slice_dir / "log.txt").read_text()
        text = (specs / "api.md").read_text()
        assert "line 1, the phase's" in text
        assert "line 5, left uncommitted" in text
        assert "line 10, origin's" not in text
        writer = next(p for role, p in r.prompts if role == "code-writer")
        assert ("origin/main is 1 commit(s) ahead of the local main this "
                "phase's branch was cut from; they touch `api.md`, which this "
                "phase names. The driver has neither merged nor rebased.") \
            in flat(writer)


def test_a_base_checked_out_nowhere_moves_by_ref_and_one_checked_out_elsewhere_stays():
    if shutil.which("git") is None:
        return
    with tempfile.TemporaryDirectory() as tmp, plain_git():
        slice_dir, repo, other = real_code_slice(tmp)
        tip = pushed(other, "src/other.py", "other\n")
        sh(repo, "fetch", "-q")
        was = sh(repo, "rev-parse", "main")
        sh(repo, "checkout", "-q", "--detach")
        elsewhere = (Path(tmp) / "elsewhere-worktree").resolve()
        sh(repo, "worktree", "add", "-q", str(elsewhere), "main")
        r = RealGitLoop(slice_dir, [], repo_root=repo)
        r._sync_base("1", repo, "main")
        assert sh(repo, "rev-parse", "main") == was
        assert ("[P1] main left 1 commit(s) behind origin/main in repo: "
                f"checked out in {elsewhere}") \
            in (slice_dir / "log.txt").read_text()
        sh(repo, "worktree", "remove", str(elsewhere))
        r._sync_base("1", repo, "main")
        assert sh(repo, "rev-parse", "main") == tip
        assert "[P1] main fast-forwarded 1 commit(s) to origin/main in repo" \
            in (slice_dir / "log.txt").read_text()


def test_no_origin_moves_nothing_and_tells_no_writer():
    if shutil.which("git") is None:
        return
    with tempfile.TemporaryDirectory() as tmp, plain_git():
        slice_dir, repo, _ = real_code_slice(tmp)
        sh(repo, "remote", "remove", "origin")
        was = sh(repo, "rev-parse", "main")
        seen = {}
        r = FetchingLoop(slice_dir, [(*V["exec_done"], cuts_and_commits(seen)),
                                     V["review_signoff"],
                                     V["consult_complete"]], repo_root=repo)
        assert run_to_exit(r) == 0
        assert seen["cut_from"] == was
        log = (slice_dir / "log.txt").read_text()
        for words in ("fast-forwarded", "diverged", "behind origin"):
            assert words not in log
        assert not any(AHEAD_WORDS in p for _, p in r.prompts)


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
        # like any target repo the driver points an agent at, and the merge
        # still measures the branch against its LOCAL base)
        assert not [c for root, c in r.fake_git.calls
                    if c[0] == "rev-list" and str(root) == str(specs)
                    and any(a.startswith("origin/") for a in c)]


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
        report = entries_in_full(slice_dir)
        assert "Push Sibling by hand when its hold lifts" in report
        assert "a push deploys dev and prd together" in report
        assert "**Proposal:** Push it when the hold lifts." in report
        assert load_state(slice_dir)["holds_reported"] == [str(sib)]
        # the invoking repo is not held, so the doc phase still pushes it
        pushes = r.fake_git.mutations("push")
        assert pushes and pushes[-1][0] == repo


def test_a_hold_the_plan_loop_seeded_is_noted_not_entered_twice():
    # The plan loop enters the hold at planning's exit 0 under the headline
    # the push check writes; the run adds its word to that entry instead.
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo, sib = held_sibling_slice(tmp)
        run_loop.init_report(slice_dir)
        run_loop.append_entry(
            slice_dir, "Outstanding actions",
            "Push Sibling by hand when its hold lifts", "seeded at planning",
            consequence="c", provenance="read — seeded by the plan loop")
        r = ScriptedLoop(slice_dir,
                         [V["exec_done"], V["review_signoff"], *TAIL],
                         repo_root=repo)
        r.fake_git.unpushed[str(sib)] = "2"
        r._nudge = _never_nudge
        assert run_to_exit(r) == 0
        assert (slice_dir / "close-out.md").read_text().count(
            "Push Sibling by hand when its hold lifts") == 1
        report = entries_in_full(slice_dir)
        assert report.count("Push Sibling by hand when its hold lifts") == 1
        assert "seeded at planning" in report
        assert "driver, push check" in report and "held as planned" in report
        assert load_state(slice_dir)["holds_reported"] == [str(sib)]


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


def test_merge_records_the_phases_landed_range():
    """The ff-merge is the one moment the phase's own commits are bounded:
    the branch's merge base is the base branch's sha just before the merge,
    the head is the branch tip. Both go on the phase's record — everything
    downstream reads the slice's shipped diff from there, never from the base
    branch since the slice began (which in parallel lanes carries the other
    lanes' merges)."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r = ScriptedLoop(slice_dir,
                         [V["exec_done"], V["review_signoff"], *TAIL],
                         repo_root=repo)
        assert run_to_exit(r) == 0
        assert load_state(slice_dir)["phases"]["1"]["landed"] == {
            "root": str(repo), "base": "base123", "head": "abc123"}


def merge_base_is_the_branch_once_merged(loop):
    """The fake git answering `merge-base <base> <branch>` as git does once
    the branch is in the base: with the branch's own head."""
    fake = loop.fake_git

    def git(*args, root=None, check=True):
        if args[0] == "merge-base" and fake.mutations("merge"):
            fake.calls.append((root, args))
            return fake.head
        return fake(*args, root=root, check=check)

    loop.git = git


def test_the_landed_base_is_the_merge_base_before_the_merge():
    """The landed record's base is re-taken at the merge (AIWF-104), and
    taken before it: after the merge, the merge base is the branch's head,
    and the range would be empty."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r = ScriptedLoop(slice_dir,
                         [V["exec_done"], V["review_signoff"], *TAIL],
                         repo_root=repo)
        r.fake_git.merge_base = NEW_MB
        merge_base_is_the_branch_once_merged(r)
        assert run_to_exit(r) == 0
        assert r.fake_git.mutations("merge")
        assert load_state(slice_dir)["phases"]["1"]["landed"] == {
            "root": str(repo), "base": NEW_MB, "head": "abc123"}


# -- a base that moved under the branch ---------------------------------------
#
# The merge is `checkout <base>` + `merge --ff-only`, so a parallel session
# that lands on the base between the review and the merge kills the
# fast-forward. Rebasing by hand afterwards puts the record's shas on neither
# branch nor base, which the resume reads as lost work.

def moved_base(loop, count, rebased_to="new222", branch="phase/074-P1"):
    """A base branch that gained `count` commits while the phase ran, and the
    sha the phase branch takes when it rebases onto it."""
    loop.fake_git.ahead[f"{branch}..main"] = count
    loop.fake_git.revs[branch] = "old111"
    loop.fake_git.rebased_head = rebased_to


def test_a_moved_base_is_rebased_and_the_record_repointed_before_the_merge():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r = ScriptedLoop(slice_dir,
                         [V["exec_done"], V["review_signoff"], *TAIL],
                         repo_root=repo)
        moved_base(r, "2")
        r.fake_git.merge_base = "mb-before"
        r.fake_git.rebased_merge_base = "mb-after"
        assert run_to_exit(r) == 0
        # the phase's own rebase, before the doc landing's later one
        assert [c for _, c in r.fake_git.mutations("rebase")][0] \
            == ("rebase", "main")
        ps = load_state(slice_dir)["phases"]["1"]
        # the review's head and base follow the rebase; the gate's green
        # does not — it is dropped, so the merge stage re-gates the
        # reordered commits
        assert ps["reviewed_head"] == "new222"
        assert ps["reviewed_base"] == "mb-after"
        assert r.gate_calls == [("1", True), ("1", True)]
        assert ps["gate_green_commit"] == "new222"
        # the landed range is measured from the merge base as it is AFTER
        # the rebase, not the one read when the phase started
        assert ps["landed"] == {"root": str(repo), "base": "mb-after",
                                "head": "new222"}
        assert [c for _, c in r.fake_git.mutations("merge")][0] \
            == ("merge", "--ff-only", "phase/074-P1")
        assert "main moved by 2 commit(s) under phase/074-P1" \
            in (slice_dir / "log.txt").read_text()


def test_a_base_that_did_not_move_is_never_rebased():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp, config=rc(test=False, doc=False))
        r = ScriptedLoop(slice_dir,
                         [V["exec_done"], V["review_signoff"],
                          V["consult_complete"]],
                         repo_root=repo)
        assert run_to_exit(r) == 0
        assert not r.fake_git.mutations("rebase")
        assert r.gate_calls == [("1", True)]


def test_a_branch_that_will_not_rebase_onto_the_moved_base_bails():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r = ScriptedLoop(slice_dir, [V["exec_done"], V["review_signoff"]],
                         repo_root=repo)
        moved_base(r, "3")
        r.fake_git.fails.add(("rebase", "main"))
        assert run_to_exit(r) == 3
        bail = json.loads((slice_dir / "bailout.json").read_text())
        assert bail["reason"] == "blocked" and bail["phase"] == "1"
        assert "moved by 3 commit(s)" in bail["details"]
        assert "does not rebase onto it cleanly" in bail["details"]
        assert ("rebase", "--abort") in [c for _, c in r.fake_git.calls]
        assert not r.fake_git.mutations("merge")
        # the request is on the record, for the resume to recognise
        req = load_state(slice_dir)["phases"]["1"]["rebase_requested"]
        assert (req["base"], req["from"]) == ("main", "old111")


def test_a_rebase_that_changes_the_phases_diff_bails():
    """The one thing the rebase must not do is alter what the phase ships:
    proven by diffing the phase's own range before and after."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r = ScriptedLoop(slice_dir, [V["exec_done"], V["review_signoff"]],
                         repo_root=repo)
        moved_base(r, "1")
        r.fake_git.diffs = ["- a\n+ b\n", "- a\n+ c\n"]
        assert run_to_exit(r) == 3
        bail = json.loads((slice_dir / "bailout.json").read_text())
        assert bail["reason"] == "blocked" and bail["phase"] == "1"
        assert "changed the phase's diff" in bail["details"]
        assert "left rebased on new222" in bail["details"]
        assert not r.fake_git.mutations("merge")
        ps = load_state(slice_dir)["phases"]["1"]
        assert ps["rebase_requested"]["from"] == "old111"
        assert ps["reviewed_head"] == "abc123", "not repointed by the bail"


def test_a_rebase_the_driver_asked_for_is_taken_on_resume():
    """AIWF-7: the driver asked for a rebase and then refused the rebased
    branch as lost work, offering only lossy remedies — here a signoff four
    rounds in. Done as asked, the review stands, its head follows the
    branch, and the merge re-runs the gate over the rewritten commits."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r1 = ScriptedLoop(slice_dir, [V["exec_done"], V["review_signoff"]],
                          repo_root=repo)
        moved_base(r1, "3")
        r1.fake_git.fails.add(("rebase", "main"))
        assert run_to_exit(r1) == 3
        # The operator rebases by hand: the reviewed commit is on neither
        # the branch nor the base, and the branch now carries main's tip.
        r2 = ScriptedLoop(slice_dir, list(TAIL), resume=True, repo_root=repo)
        r2.fake_git.branches.add("phase/074-P1")
        r2.fake_git.lost.add("abc123")
        r2.fake_git.head = "new333"
        assert run_to_exit(r2) == 0
        ps = load_state(slice_dir)["phases"]["1"]
        assert ps["status"] == "merged"
        assert ps["reviewed_head"] == "new333"
        assert "rebase_requested" not in ps
        assert r2.gate_calls == [("1", True)], "the gate re-runs"
        assert ps["gate_green_commit"] == "new333"
        assert [s[0] for s in r2.spawned] == ["consult", "test-agent",
                                              "doc-writer"], "no re-review"
        assert ("branch rebased by hand as the driver asked (old111 → "
                "new333); the review stands, the gate re-runs") \
            in (slice_dir / "log.txt").read_text()


def rebase_requested_state(**phase):
    state = resume_state(PROJECT, stage="merging")
    state["phases"]["1"].update(
        review_rounds=4, reviewed_head="old111", gate_green_commit="old111",
        **phase)
    return state


def test_a_requested_rebase_not_yet_done_asks_again_and_no_request_is_lost_work():
    ask = {"base": "main", "from": "old111", "ts": "t"}
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        (slice_dir / "state.json").write_text(
            json.dumps(rebase_requested_state(rebase_requested=ask)))
        r = ScriptedLoop(slice_dir, [], resume=True, repo_root=repo)
        r.fake_git.branches.add("phase/074-P1")
        r.fake_git.lost.add("old111")
        r.fake_git.not_in.add(("main", "phase/074-P1"))
        assert run_to_exit(r) == 3
        bail = json.loads((slice_dir / "bailout.json").read_text())
        assert bail["reason"] == "blocked" and bail["phase"] == "1"
        assert "waits on the rebase the driver asked for" in bail["details"]
        assert "Rebase phase/074-P1 onto main" in bail["details"]
        ps = load_state(slice_dir)["phases"]["1"]
        assert ps["rebase_requested"] == ask
        assert ps["reviewed_head"] == "old111"
        assert not r.gate_calls and not r.fake_git.mutations("merge")

    # Without the request, the same branch is lost work, exactly as before.
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        (slice_dir / "state.json").write_text(
            json.dumps(rebase_requested_state()))
        r = ScriptedLoop(slice_dir, [], resume=True, repo_root=repo)
        r.fake_git.branches.add("phase/074-P1")
        r.fake_git.lost.add("old111")
        assert run_to_exit(r) == 3
        bail = json.loads((slice_dir / "bailout.json").read_text())
        assert bail["reason"] == "lost_work"
        assert load_state(slice_dir)["phases"]["1"]["reviewed_head"] \
            == "old111"


def test_doc_phase_prompt_states_diff_files_digest_verbs_and_doc():
    """The doc-writer's dispatch carries the driver's deterministic facts:
    the diff on disk per repo, a section per merged phase (stat, then that
    phase's own diff, over the range the phase landed — never the base
    branch, and never HEAD, which is the doc branch), the whole-plan digest
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
        # the diff file: stat on top, then the diff, over P1's landed range
        diff_file = slice_dir / "doc_phase" / "repo.diff"
        text = diff_file.read_text()
        assert text.startswith(f"{repo} — P1: git diff base123..abc123\n")
        assert text.index(" a.py | 2 +-") < text.index("diff --git a/a.py")
        assert (f"- {repo}: {diff_file} (P1: "
                "1 file changed, 1 insertion(+), 1 deletion(-))") in prompt
        assert [c for _, c in r.fake_git.calls
                if c[:2] == ("diff", "base123..abc123")]
        assert not [c for _, c in r.fake_git.calls if c[0] == "diff"
                    and any("main" in a or "HEAD" in a for a in c)]
        # the whole-plan digest, with the done-record and not the intent
        assert "# Orientation digest — the whole slice" in prompt
        assert "**Done (P1).** Shipped the thing" in prompt
        assert "not the writer's" not in prompt
        assert "slice.md is not your input" in prompt
        # the close-out verbs' argument shapes, from the tool's own parser,
        # once each — all in the dispatch line
        assert prompt.count("close_out.py append <close-out.md> --kind {") == 1
        assert "--consequence: what an operator or user experiences" in prompt
        line = close_out.dispatch_line(slice_dir / "close-out.md")
        assert f"- {line}\n- Work on branch" in prompt
        assert "The other verbs" not in prompt
        assert prompt.count("close_out.py note <close-out.md> <id> --by BY") == 1
        assert prompt.count("close_out.py strike <close-out.md> <id>") == 1
        assert "close_out.py strike <close-out.md> <id> --reason REASON" in prompt
        assert ("--reason: why — resolved/refuted names the commit and the "
                "re-run") in prompt
        # the report is rendered, never written by hand: no Summary, no Focus
        assert "Focus" not in prompt and "Summary" not in prompt


def test_doc_phase_diff_rows_name_unchanged_repos_without_a_file():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        script = [V["exec_done"], V["review_signoff"], *TAIL]
        r = ScriptedLoop(slice_dir, script, repo_root=repo)
        assert run_to_exit(r) == 0
        prompt = next(p for role, p in r.prompts if role == "doc-writer")
        assert f"- {repo}: no changes (P1)" in prompt
        # the folder's own .gitignore, and no diff file
        assert [f.name for f in (slice_dir / "doc_phase").iterdir()] == [
            ".gitignore"]


def test_doc_diffs_are_per_repo_and_hold_the_specs_slices_tree_out():
    """A slice landing in two repos gets a file per repo, each named after
    the phase that landed there — and in the specs repo the `slices/` tree is
    held out, so the driver's own run record and every parallel session's
    stay out of the shipped diff."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        specs = (Path(tmp) / "specs").resolve()
        (slice_dir / "plan.md").write_text(
            "# plan\n\n" + phase_section("1", "Code")
            + "\n" + phase_section("2", "Contract", specs_as_target(tmp)))
        script = [V["exec_done"], V["review_signoff"],
                  V["exec_done"], V["review_signoff"], *TAIL]
        r = ScriptedLoop(slice_dir, script, repo_root=repo)
        r.fake_git.stat = (" a.py | 2 +-\n"
                           " 1 file changed, 1 insertion(+), 1 deletion(-)")
        r.fake_git.diff = "diff --git a/a.py b/a.py\n@@ -1 +1 @@\n-x\n+y"
        assert run_to_exit(r) == 0
        out_dir = slice_dir / "doc_phase"
        assert sorted(f.name for f in out_dir.glob("*.diff")) == [
            "repo.diff", "specs.diff"]
        assert (out_dir / "repo.diff").read_text().startswith(
            f"{repo} — P1: git diff base123..abc123\n")
        assert (out_dir / "specs.diff").read_text().startswith(
            f"{specs} — P2: git diff base123..abc123\n")
        specs_diffs = [c for root, c in r.fake_git.calls
                       if c[0] == "diff" and str(root) == str(specs)]
        assert specs_diffs, "the specs repo's diff was never read"
        assert all(":(exclude)slices" in c for c in specs_diffs)
        # the exclusion is scoped to the repo that holds the slice folder
        assert all("--" not in c for root, c in r.fake_git.calls
                   if c[0] == "diff" and str(root) == str(repo))
        prompt = next(p for role, p in r.prompts if role == "doc-writer")
        assert f"- {repo}: {out_dir / 'repo.diff'} (P1: " in prompt
        assert f"- {specs}: {out_dir / 'specs.diff'} (P2: " in prompt


def test_doc_diff_file_carries_a_section_per_phase_in_merge_order():
    """Two phases in one repo share a file — a section each, in the order
    they merged, because the ranges are not contiguous once another lane's
    merges sit between them. The row names both."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(
            tmp, phases=[("1", "First"), ("2", "Second")])
        script = [V["exec_done"], V["review_signoff"],
                  V["exec_done"], V["review_signoff"], *TAIL]
        r = ScriptedLoop(slice_dir, script, repo_root=repo)
        r.fake_git.stat = (" a.py | 2 +-\n"
                           " 1 file changed, 1 insertion(+), 1 deletion(-)")
        r.fake_git.diff = "diff --git a/a.py b/a.py\n@@ -1 +1 @@\n-x\n+y"
        assert run_to_exit(r) == 0
        out_dir = slice_dir / "doc_phase"
        assert [f.name for f in out_dir.glob("*.diff")] == ["repo.diff"]
        text = (out_dir / "repo.diff").read_text()
        assert text.index("— P1: git diff") < text.index("— P2: git diff")
        prompt = next(p for role, p in r.prompts if role == "doc-writer")
        assert ("(P1: 1 file changed, 1 insertion(+), 1 deletion(-); "
                "P2: 1 file changed, 1 insertion(+), 1 deletion(-))") in prompt


def test_a_merged_phase_without_a_landed_range_is_named_in_the_rows():
    """A phase merged under a plugin before 0.9.16, or in the crash window
    between the ff-merge and the record, has no range to diff — after a
    fast-forward the pre-merge base sha is unrecoverable. The driver says so
    in the dispatch rather than inventing a range."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(
            tmp, phases=[("1", "First", PROJECT, True)])
        state = {
            "slice": "074_test_slice", "created_at": "t",
            "orchestrator": None, "run_phase": "docs",
            "bases": {str(repo): "main"}, "known_phases": ["1"],
            "phases": {"1": {"status": "merged", "stage": None,
                             "branch": None, "target": PROJECT,
                             "executor_rounds": 1, "gate_fix_rounds": 0,
                             "review_rounds": 1, "gate_runs": 1,
                             "gate_green_commit": "abc123",
                             "gate_green_log": "x",
                             "reviewed_head": "abc123"}},
            "generation": 0, "test_rounds": 1, "consult_seq": 1,
            "in_flight": None, "history": [],
            "doc_phase": {"stage": "writer", "gate_runs": 0, "nudges": 0,
                          "session": None},
        }
        (slice_dir / "state.json").write_text(json.dumps(state))
        r = ScriptedLoop(slice_dir, [V["doc_done"]], resume=True,
                         repo_root=repo)
        assert run_to_exit(r) == 0
        prompt = next(p for role, p in r.prompts if role == "doc-writer")
        assert "- P1: merged with no range on record" in prompt
        assert not [c for _, c in r.fake_git.calls if c[0] == "diff"]
        assert not list((slice_dir / "doc_phase").glob("*.diff"))


# -- a phase's commits outside its Target in the doc diff (AIWF-67) -----------
#
# Ansible slice 057's P6 and P7 each corrected a runbook in /work/Ansible, the
# repo P3 landed in, and listed the commit in their `Review:` ledgers beside
# commits in /work/scratch/TerraformState, which no phase targets. Ansible's
# doc diff carried P3's section alone: the corrections were on the doc branch
# and went undocumented.

LEDGER_SUMMARY = "1 file changed, 1 insertion(+), 1 deletion(-)"


def doc_phase_resume(slice_dir, repo, phases):
    """A run resumed at the doc phase's writer with every phase merged —
    `phases` maps each id to what its record carries beyond that (`landed`,
    the review-set snapshots)."""
    record = {"status": "merged", "stage": None, "branch": None,
              "target": PROJECT, "executor_rounds": 1, "gate_fix_rounds": 0,
              "review_rounds": 1, "gate_runs": 1,
              "gate_green_commit": "abc123", "gate_green_log": "x",
              "reviewed_head": "abc123"}
    state = {
        "slice": "074_test_slice", "created_at": "t", "orchestrator": None,
        "run_phase": "docs", "bases": {str(repo): "main"},
        "known_phases": list(phases),
        "phases": {pid: {**record, **extra} for pid, extra in phases.items()},
        "generation": 0, "test_rounds": 1, "consult_seq": 1,
        "in_flight": None, "history": [],
        "doc_phase": {"stage": "writer", "gate_runs": 0, "nudges": 0,
                      "session": None},
    }
    (slice_dir / "state.json").write_text(json.dumps(state))


def landed_in(repo, base, head):
    return {"landed": {"root": str(repo), "base": base, "head": head}}


def one_line_diff(name):
    return f"diff --git a/{name} b/{name}\n@@ -1 +1 @@\n-x\n+y"


def test_a_ledgers_commits_join_the_doc_diff_after_the_landed_sections():
    """Slice 057's shape: P1 lands in the repo, and so does P2, whose ledger
    gained a commit there, one in a clone no phase targets, the first again
    under a path inside the repo, and one P1's range already carries. A
    pair the ledger held when P2 began is not P2's."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp, phases=[
            ("1", "Roles", PROJECT, True),
            ("2", "Runbook", PROJECT, True, "Review: ledger.md\n")])
        tf = Path(tmp) / "scratch" / "TerraformState"
        tf.mkdir(parents=True)
        roles = repo / "roles"
        roles.mkdir()
        (slice_dir / "ledger.md").write_text(ledger(
            ("Old", "/work/scratch/Old", SHA_B2),
            ("Ansible", str(repo), SHA_A),
            ("TerraformState", str(tf), SHA_B),
            ("Ansible", str(roles), SHA_A),
            ("Ansible", str(repo), SHA_C)))
        doc_phase_resume(slice_dir, repo, {
            "1": landed_in(repo, "base123", "abc123"),
            "2": {**landed_in(repo, "abc123", "def456"),
                  "review_set_start": [["/work/scratch/Old", SHA_B2]],
                  "review_set_ambiguous_start": []}})
        r = ScriptedLoop(slice_dir, [V["doc_done"]], resume=True,
                         repo_root=repo)
        g = r.fake_git
        g.toplevels = {str(repo): str(repo), str(roles): str(repo),
                       str(tf): str(tf)}
        g.parents = {SHA_A: "a1" * 20, SHA_B: "b1" * 20, SHA_C: "c1" * 20}
        # P1's range carries SHA_C: its head reaches it, its base does not
        g.merged.add(SHA_C)
        g.not_in.add((SHA_C, "base123"))
        g.stat = f" a.py | 2 +-\n {LEDGER_SUMMARY}"
        g.diffs = [one_line_diff(name)
                   for name in ("p1.py", "p2.py", "runbook.md", "main.tf")]
        assert run_to_exit(r) == 0
        out_dir = slice_dir / "doc_phase"
        assert sorted(f.name for f in out_dir.glob("*.diff")) == [
            "TerraformState.diff", "repo.diff"]
        text = (out_dir / "repo.diff").read_text()
        assert [line for line in text.splitlines()
                if line.startswith(f"{repo} — ")] == [
            f"{repo} — P1: git diff base123..abc123",
            f"{repo} — P2: git diff abc123..def456",
            f"{repo} — P2, ledger ledger.md: git diff a1a1a1a1a1a1.."
            f"{SHA_A[:12]}"]
        assert text.endswith(f"{SHA_A[:12]}\n\n{g.stat}\n\n"
                             + one_line_diff("runbook.md") + "\n")
        assert (out_dir / "TerraformState.diff").read_text() == (
            f"{tf} — P2, ledger ledger.md: git diff b1b1b1b1b1b1.."
            f"{SHA_B[:12]}\n\n{g.stat}\n\n" + one_line_diff("main.tf") + "\n")
        # the pair from before P2 and the commit P1's range carries are
        # diffed nowhere
        assert not [c for _, c in g.calls if c[0] == "diff" and any(
            SHA_B2 in a or SHA_C in a for a in c)]
        prompt = next(p for role, p in r.prompts if role == "doc-writer")
        assert (f"- {repo}: {out_dir / 'repo.diff'} (P1: {LEDGER_SUMMARY}; "
                f"P2: {LEDGER_SUMMARY}; P2 ledger {SHA_A[:12]}: "
                f"{LEDGER_SUMMARY})\n"
                f"- {tf}: {out_dir / 'TerraformState.diff'} (P2 ledger "
                f"{SHA_B[:12]}: {LEDGER_SUMMARY}) — no phase's Target: the "
                "driver pushes no doc edit there, so a doc this needs goes in "
                "the close-out report\n- The plan is") in prompt
        assert "/work/scratch/Old" not in prompt


def test_ledger_lines_the_driver_cannot_diff_are_named_and_in_no_file():
    """A gained line naming a path that is no checkout (missing, or a plain
    directory), a commit its clone does not have, a root commit, or more
    than one commit is a row of its own after the phases' rows — P2 merged
    with no range on record, and its ledger is read all the same. A line
    naming two commits the ledger held when P2 began is not P2's."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp, phases=[
            ("1", "Roles", PROJECT, True),
            ("2", "Runbook", PROJECT, True, "Review: ledger.md\n")])
        gone, plain = Path(tmp) / "gone", Path(tmp) / "plain"
        plain.mkdir()
        (slice_dir / "ledger.md").write_text(
            ledger(("Gone", str(gone), SHA_A), ("Plain", str(plain), SHA_A),
                   ("Ansible", str(repo), SHA_B),
                   ("Ansible", str(repo), SHA_C))
            + bump_row(str(repo), SHA_B2, SHA_A)
            + bump_row("/work/scratch/Old", SHA_B, SHA_B2))
        doc_phase_resume(slice_dir, repo, {
            "1": landed_in(repo, "base123", "abc123"),
            "2": {"review_set_start": [], "review_set_ambiguous_start": [
                ["/work/scratch/Old", [SHA_B, SHA_B2]]]}})
        r = ScriptedLoop(slice_dir, [V["doc_done"]], resume=True,
                         repo_root=repo)
        g = r.fake_git
        g.toplevels = {str(repo): str(repo), str(plain): ""}
        g.parents = {SHA_A: "a1" * 20}   # SHA_C has none: a root commit
        g.fails.add(("rev-parse", "--verify", "--quiet", f"{SHA_B}^{{commit}}"))
        g.stat = f" a.py | 2 +-\n {LEDGER_SUMMARY}"
        g.diff = one_line_diff("p1.py")
        assert run_to_exit(r) == 0
        prompt = next(p for role, p in r.prompts if role == "doc-writer")
        tail = "so its changes are not in the files above"
        assert (f"- {repo}: {slice_dir / 'doc_phase' / 'repo.diff'} (P1: "
                f"{LEDGER_SUMMARY})\n"
                "- P2: merged with no range on record (an earlier plugin "
                "version, or a resume past a crash at its merge) — its changes "
                "are not in the files above\n"
                f"- P2: {gone} {SHA_A} in ledger.md — not a git checkout, "
                f"{tail}\n"
                f"- P2: {plain} {SHA_A} in ledger.md — not a git checkout, "
                f"{tail}\n"
                f"- P2: {repo} {SHA_B} in ledger.md — no such commit there, "
                f"{tail}\n"
                f"- P2: {repo} {SHA_C} in ledger.md — a root commit, with no "
                f"parent to diff against, {tail}\n"
                f"- P2: ledger.md names more than one commit for {repo} on one "
                f"line ({SHA_B2}, {SHA_A}) — the driver cannot tell which is "
                "the phase's, so none of them is in the files above\n"
                "- The plan is") in prompt
        assert "/work/scratch/Old" not in prompt
        assert [f.name for f in (slice_dir / "doc_phase").glob("*.diff")] == [
            "repo.diff"]
        text = (slice_dir / "doc_phase" / "repo.diff").read_text()
        assert text.count(f"{repo} — ") == 1
        assert not [c for _, c in g.calls if c[0] == "diff" and any(
            sha in a for a in c for sha in (SHA_A, SHA_B, SHA_C, SHA_B2))]
        log = (slice_dir / "log.txt").read_text()
        assert (f"doc phase: P2 ledger ledger.md: {gone} {SHA_A} — not a git "
                "checkout; its changes are not in the diff files\n") in log
        assert (f"doc phase: P2 ledger ledger.md: {repo} {SHA_C} — a root "
                "commit, with no parent to diff against; its changes are not "
                "in the diff files\n") in log
        assert (f"doc phase: P2 ledger ledger.md names more than one commit "
                f"for {repo} on one line ({SHA_B2}, {SHA_A}); none of them is "
                "in the diff files\n") in log


def test_a_ledger_section_is_redacted_over_its_commit_and_parent():
    """The redactor reads a ledger section's blobs at the commit's parent and
    at the commit itself. P1's own range came out empty, and the repo still
    gets a file for its ledger commit, and no `no changes` row."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp, phases=[
            ("1", "Rotate", PROJECT, True, "Review: ledger.md\n")])
        (slice_dir / "ledger.md").write_text(
            ledger(("Ansible", str(repo), SHA_A)))
        doc_phase_resume(slice_dir, repo, {
            "1": {**landed_in(repo, "base123", "abc123"),
                  "review_set_start": [], "review_set_ambiguous_start": []}})
        r = ScriptedLoop(slice_dir, [V["doc_done"]], resume=True,
                         repo_root=repo)
        g = r.fake_git
        parent = "a1" * 20
        g.toplevels = {str(repo): str(repo)}
        g.parents = {SHA_A: parent}
        diff, old, new = secret_change("S3CRETKEYVALUE", "N3WKEYVALUE00")
        g.stats = {"base123..abc123": ""}
        g.stat = f" {SECRET_PATH} | 2 +-\n {LEDGER_SUMMARY}"
        g.diff = diff
        g.blobs = {(parent, SECRET_PATH): old, (SHA_A, SECRET_PATH): new}
        assert run_to_exit(r) == 0
        path = slice_dir / "doc_phase" / "repo.diff"
        text = path.read_text()
        assert text.startswith(
            f"{repo} — P1, ledger ledger.md: git diff {parent[:12]}.."
            f"{SHA_A[:12]}\n\n {SECRET_PATH} | 2 +-\n")
        assert text.splitlines()[-3:] == [
            "-[Secret ca-key: 1 data line]", "+[Secret ca-key: 1 data line]",
            " [Secret ca-key: 1 data line]"]
        shows = [c for _, c in g.calls if c[0] == "show"]
        assert ("show", f"{parent}:{SECRET_PATH}") in shows
        assert ("show", f"{SHA_A}:{SECRET_PATH}") in shows
        assert_no_secret_on_disk(slice_dir)
        prompt = next(p for role, p in r.prompts if role == "doc-writer")
        assert (f"- {repo}: {path} (P1 ledger {SHA_A[:12]}: "
                f"{LEDGER_SUMMARY})\n- The plan is") in prompt
        assert f"- {repo}: no changes" not in prompt
        assert (f"doc phase: 3 Secret data line(s) stubbed in {path}"
                in (slice_dir / "log.txt").read_text())


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
            "bases": {str(repo): "main"},
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


# -- the doc commits a multi-repo slice leaves in its other repos ------------
#
# The doc branch exists in the primary repo only, and the test phase pushed
# every other repo before the doc phase began — so a doc commit the writer
# made in a sibling sat on its local base, unpushed and unreported (AIWF-11).

def began_at(loop, sib):
    """The sha the doc phase recorded for the sibling's base as it began."""
    return loop.state["doc_phase"]["sibling_heads"][str(sib)]


def doc_writer_commits_in(sib, behind=None, then=None):
    """The doc-writer's script step: done, having committed one doc commit
    on the sibling's base — whose origin has meanwhile gained `behind`
    commits of its own, when given, on top of the commit the doc phase
    began from — and `then`, whatever else happened meanwhile."""
    def effect(loop):
        loop.fake_git.unpushed[str(sib)] = "1"
        if behind:
            loop.fake_git.ahead["main..origin/main"] = behind
            loop.fake_git.merged.add(began_at(loop, sib))
        if then:
            then(loop)
    return ("doc-writer", {"outcome": "done", "summary": "docs"}, effect)


def sibling_doc_script(sib, behind=None, then=None):
    return [V["exec_done"], V["review_signoff"], V["consult_complete"],
            V["test_clean"], doc_writer_commits_in(sib, behind, then)]


def test_the_doc_landing_pushes_a_siblings_doc_commits_under_the_lease():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo, sib = sibling_phase_slice(tmp)
        (repo / ".aiworkflowrc").write_text(rc(devlock=True))
        (slice_dir.parent.parent / "scripts").mkdir()
        r = ScriptedLoop(slice_dir, sibling_doc_script(sib), repo_root=repo)
        at_push = watch_push_holder(
            r, slice_dir.parent.parent / "scripts" / "dev-holder")
        assert run_to_exit(r) == 0
        # the primary lands first, then the sibling goes out — both under
        # the one hold the landing took
        assert pushes(r) == [(str(repo), "main"), (str(sib), "main")]
        assert at_push == [True, True]
        log = (slice_dir / "log.txt").read_text()
        assert log.count("devlock ACQUIRED (slice 074 doc landing)") == 1
        assert log.count("devlock released") == 2
        assert f"pushed main in {sib} (1 commit(s)" in log
        # fetched right before it was measured against origin
        calls = [c for root, c in r.fake_git.calls if str(root) == str(sib)]
        last_fetch = max(i for i, c in enumerate(calls)
                         if c == ("fetch", "origin"))
        assert last_fetch < max(i for i, c in enumerate(calls)
                                if c[0] == "push")
        assert load_state(slice_dir)["doc_phase"]["stage"] == "done"
        # and the writer was told where a sibling doc edit goes
        prompt = next(p for role, p in r.prompts
                      if role == "doc-writer").replace("\n", " ")
        assert f"which is checked out in {repo} — the one repo" in prompt
        assert "never on a new branch; the driver pushes it" in prompt
        assert "Never push" in prompt


def test_a_held_siblings_doc_commits_are_reported_not_pushed():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo, sib = held_sibling_slice(tmp)
        r = ScriptedLoop(slice_dir, sibling_doc_script(sib), repo_root=repo)
        assert run_to_exit(r) == 0
        assert pushes(r) == [(str(repo), "main")]
        assert "Push Sibling by hand when its hold lifts" \
            in load_report(slice_dir)


def test_a_held_primary_still_pushes_a_siblings_doc_commits_under_the_lease():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo, sib = sibling_phase_slice(tmp)
        (repo / ".aiworkflowrc").write_text(rc(devlock=True))
        (slice_dir.parent.parent / "scripts").mkdir()
        (slice_dir / "plan.md").write_text(
            f"# plan\n\n## Push holds\n\n- {PROJECT} — prd rolls on this "
            "push\n\n" + phase_section("1", "Chart change", "../Sibling"))
        r = ScriptedLoop(slice_dir, sibling_doc_script(sib), repo_root=repo)
        at_push = watch_push_holder(
            r, slice_dir.parent.parent / "scripts" / "dev-holder")
        assert run_to_exit(r) == 0
        assert pushes(r) == [(str(sib), "main")]
        assert at_push == [True]
        assert "devlock ACQUIRED (slice 074 doc landing)" \
            in (slice_dir / "log.txt").read_text()
        assert not (slice_dir.parent.parent / "scripts"
                    / "dev-holder").exists(), "released at end"


def test_a_project_that_never_pushes_leaves_sibling_doc_commits_local():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo, sib = sibling_phase_slice(tmp)
        (repo / ".aiworkflowrc").write_text(rc(push=False))
        r = ScriptedLoop(slice_dir, sibling_doc_script(sib), repo_root=repo)
        assert run_to_exit(r) == 0
        assert pushes(r) == []
        assert "doc commits in Sibling stay local" \
            in (slice_dir / "log.txt").read_text()


# A sibling whose origin moved after the test phase pushed it — CI's image-pin
# bot committing to a deploy repo's main — left the doc commit on a stale local
# main that could not go out as a fast-forward (AIWF-41). The doc phase records
# where each sibling's base began; when origin carries that commit, everything
# only the local base holds is the run's own, and the driver rebases it.

def diverged_sibling_run(tmp, then=None):
    """A slice whose doc-writer committed in a sibling whose origin has
    since gained two commits of its own — and `then`, whatever else."""
    slice_dir, repo, sib = sibling_phase_slice(tmp)
    r = ScriptedLoop(slice_dir, sibling_doc_script(sib, behind="2",
                                                   then=then),
                     repo_root=repo)
    return slice_dir, repo, sib, r


def calls_in(r, root):
    return [c for at, c in r.fake_git.calls if str(at) == str(root)]


def refuse_in(loop, where, argv):
    """Make git refuse `argv` in the repo at `where` alone — `fails` refuses
    it in every repo, and the primary's landing runs the same rebase."""
    inner = loop.git

    def git(*args, root=None, check=True):
        if str(root) != str(where) or args != argv:
            return inner(*args, root=root, check=check)
        loop.fake_git.fails.add(argv)
        try:
            return inner(*args, root=root, check=check)
        finally:
            loop.fake_git.fails.discard(argv)

    loop.git = git


def assert_sibling_blocked(r, slice_dir, repo, sib, why, rebased=False):
    """The run bailed `blocked` at the sibling, naming `why`: the primary
    landed and went out, the sibling was never pushed — nor rebased, unless
    the rebase is what failed — and the ladder waits at its pushes for the
    resume."""
    assert run_to_exit(r) == 3
    bail = json.loads((slice_dir / "bailout.json").read_text())
    assert bail["reason"] == "blocked" and not bail["question"]
    assert str(sib) in bail["details"] and why in bail["details"]
    assert pushes(r) == [(str(repo), "main")]
    assert load_state(slice_dir)["doc_phase"]["stage"] == "siblings"
    if not rebased:
        assert "push it by hand, then resume" in bail["details"]
        assert not [c for c in calls_in(r, sib) if c[0] == "rebase"]


def test_a_sibling_origin_moved_under_is_rebased_onto_it_and_pushed():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo, sib, r = diverged_sibling_run(tmp)
        assert run_to_exit(r) == 0
        assert pushes(r) == [(str(repo), "main"), (str(sib), "main")]
        # rebased in the sibling, after the fetch and before the push
        calls = calls_in(r, sib)
        rebase = calls.index(("rebase", "origin/main"))
        assert max(i for i, c in enumerate(calls)
                   if c == ("fetch", "origin")) < rebase
        assert rebase < calls.index(("push", "origin", "main"))
        assert ("rebase", "--abort") not in calls
        ds = load_state(slice_dir)["doc_phase"]
        assert list(ds["sibling_heads"]) == [str(sib)]
        assert ds["stage"] == "done"
        log = (slice_dir / "log.txt").read_text()
        assert (f"rebased 1 commit(s) of main in {sib} onto origin/main "
                "(2 commit(s) origin gained meanwhile)") in log
        assert f"pushed main in {sib} (1 commit(s)" in log


def test_a_diverged_sibling_with_no_record_of_its_start_blocks():
    """A run whose doc phase began before the record existed cannot tell
    the run's own commits from anyone else's — today's bail."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo, sib, r = diverged_sibling_run(
            tmp, then=lambda loop: loop.state["doc_phase"].pop(
                "sibling_heads"))
        assert_sibling_blocked(r, slice_dir, repo, sib,
                               "the run has no record of where the doc "
                               "phase began there")


def test_a_sibling_whose_origin_lacks_its_start_blocks_and_the_resume_pushes_it_alone():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo, sib, r = diverged_sibling_run(
            tmp, then=lambda loop: loop.fake_git.not_in.add(
                (began_at(loop, sib), "origin/main")))
        assert_sibling_blocked(r, slice_dir, repo, sib,
                               "origin does not carry the commit the doc "
                               "phase began from")

        # the operator settles the sibling's base; the resume owes only its
        # push — no session, no second landing of the primary
        r2 = ScriptedLoop(slice_dir, [], resume=True, repo_root=repo)
        r2.fake_git.unpushed[str(sib)] = "1"
        assert run_to_exit(r2) == 0
        assert not r2.spawned
        assert pushes(r2) == [(str(sib), "main")]
        for verb in ("rebase", "merge"):
            assert not r2.fake_git.mutations(verb)
        assert load_state(slice_dir)["doc_phase"]["stage"] == "done"


def test_a_diverged_sibling_on_another_branch_blocks():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo, sib, r = diverged_sibling_run(
            tmp, then=lambda loop: loop.fake_git.branch_at.update(
                {str(sib): "hotfix"}))
        assert_sibling_blocked(r, slice_dir, repo, sib,
                               "main is not checked out there")


def test_a_diverged_sibling_with_a_dirty_worktree_blocks():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo, sib, r = diverged_sibling_run(
            tmp, then=lambda loop: loop.fake_git.dirty_roots.update(
                {str(sib): " M values.yaml"}))
        assert_sibling_blocked(r, slice_dir, repo, sib,
                               "the worktree there is dirty")


def test_a_sibling_rebase_that_conflicts_is_aborted_and_blocks():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo, sib, r = diverged_sibling_run(tmp)
        refuse_in(r, sib, ("rebase", "origin/main"))
        assert_sibling_blocked(r, slice_dir, repo, sib,
                               "do not rebase cleanly onto origin/main",
                               rebased=True)
        assert "resolve by hand, push, then resume" in json.loads(
            (slice_dir / "bailout.json").read_text())["details"]
        assert [c for c in calls_in(r, sib) if c[0] == "rebase"] == [
            ("rebase", "origin/main"), ("rebase", "--abort")]


# -- the wrap-up ----------------------------------------------------------------
#
# One `dev:wrap-up` session between the doc-writer and the gate sweep, on
# branches of its own, landed with the doc phase or left out whole — and never
# a reason to stop a run (run-loop.md § After the last phase). The session is
# faked at `run_kc_session` (ScriptedLoop.run); from the hand-back before it on,
# the repos run on FakeGit's ref model, so what reached which branch can be
# read off the refs.

WRAP = "phase/074-wrap-up"
DOCS = "phase/074-docs"
WRAP_DONE = {"outcome": "done", "summary": "fixed B1", "fixed": ["B1"],
             "words": ["P2"], "left": [], "unknown_key": "ignored"}


def plant_waiting(slice_dir):
    """An entry the table gives the wrap-up: an unlabelled defect, which it
    labels from its text."""
    close_out.init_report(slice_dir)
    close_out.append_entry(slice_dir, "Bugs", "a page reads wrong", "body",
                           consequence="the page misleads a reader",
                           provenance="read P1")


def model_repos(loop, repo, *siblings, docs=True):
    """FakeGit's ref model for the repos the wrap-up works in, switched on
    at the hand-back before it: the primary's base (and doc branch, one
    commit up), each sibling's base, their origins level with them."""
    g = loop.fake_git
    g.refs[str(repo)] = {"main": "m0", "origin/main": "m0"}
    if docs:
        g.refs[str(repo)][DOCS] = "d0"
        g.parents["d0"] = "m0"
    g.dirty_roots[str(repo)] = ""
    for sib in siblings:
        g.refs[str(sib)] = {"main": "s0", "origin/main": "s0"}
        g.dirty_roots[str(sib)] = ""
        g.branch_at[str(sib)] = "main"


def wrap_script(repo, *siblings):
    """The run up to the wrap-up, the doc-writer's hand-back switching the
    ref model on."""
    return [V["exec_done"], V["review_signoff"], V["consult_complete"],
            V["test_clean"],
            ("doc-writer", {"outcome": "done", "summary": "docs"},
             lambda loop: model_repos(loop, repo, *siblings))]


def wrap_up_fixes(repo=None, sib=None, then=None):
    """The wrap-up's session on disk: a commit on its branch in each repo
    given, B1 struck naming it — and `then`, whatever else it did."""
    def effect(loop):
        loop.store_at_dispatch = json.loads(
            (loop.slice_dir / "close-out.json").read_text())
        if repo:
            loop.fake_git.commit_on(repo, WRAP, "w1")
        if sib:
            loop.fake_git.commit_on(sib, WRAP, "sw1")
        close_out.strike_entry(loop.slice_dir, "B1", "fixed", by="wrap-up",
                               commit="w1")
        if then:
            then(loop)
    return effect


def left_out_event(slice_dir):
    return [e for e in json.loads((slice_dir / "close-out.json").read_text())
            ["entries"] if e["headline"].startswith(
                "The wrap-up was left out of the landing: ")]


def test_the_wrap_up_is_skipped_when_nothing_waits():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r = ScriptedLoop(slice_dir, wrap_script(repo), repo_root=repo)
        assert run_to_exit(r) == 0
        assert not r.wrap_up_sessions
        state = load_state(slice_dir)
        assert state["wrap_up"]["outcome"] == "skipped"
        assert "nothing waits for the wrap-up — skipped" \
            in (slice_dir / "log.txt").read_text()
        # the ladder goes on: the doc gate, the landing
        assert r.doc_gate_calls == [True]
        assert r.fake_git.refs[str(repo)]["main"] == "d0"
        assert state["doc_phase"]["stage"] == "done"
        assert not r.fake_git.specs_commits
        assert "wrap-up" not in load_report(slice_dir).split("\n## ")[0]


def test_a_green_wrap_up_lands_with_the_doc_phase():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo, sib = sibling_phase_slice(tmp)
        plant_waiting(slice_dir)
        r = ScriptedLoop(slice_dir, wrap_script(repo, sib), repo_root=repo,
                         wrap_ups=[(WRAP_DONE, wrap_up_fixes(repo, sib))])
        assert run_to_exit(r) == 0
        g = r.fake_git
        # cut in the primary from the doc branch's head, in the sibling from
        # its base
        assert [(str(root), c) for root, c in g.calls
                if c[:3] == ("checkout", "-b", WRAP)] == [
            (str(repo), ("checkout", "-b", WRAP, "d0")),
            (str(sib), ("checkout", "-b", WRAP, "s0"))]
        # the dispatch: the role's model and timeout, the work list, a row
        # per repo, the verbs, the spec repo and the verdict file
        [session] = r.wrap_up_sessions
        assert (session["agent"], session["model"], session["effort"],
                session["timeout"]) == ("wrap-up", "opus", "xhigh", 7200)
        prompt = session["prompt"]
        assert prompt.startswith("Slice 074_test_slice is built")
        assert ("- What waits for you, as `worklist` prints it now:\n"
                "  1 entry waits for the wrap-up\n"
                "  B1 · label — give it its labels from its text\n") in prompt
        assert (f"  - {repo} — branch {WRAP} — gate: `kc project lint`, "
                "`kc project build` and `kc project test`") in prompt
        assert (f"  - {sib} — branch {WRAP} — gate: `kc project test` from "
                f"{sib}") in prompt
        # every row naming a `--project <component>` gate says what exit 3 is
        assert prompt.count(run_loop.NOTHING_RAN_HINT) == 2
        verbs = "\n".join("  " + v for v in close_out.verb_usage(
            "worklist", "show", "list", "relabel", "propose", "fold",
            "amend").splitlines())
        assert ("  The other verbs the wrap-up uses, with their arguments:\n"
                + verbs + "\n") in prompt
        # note and strike are the dispatch line's, once
        assert prompt.count("close_out.py note <close-out.md> <id>") == 1
        assert prompt.count("close_out.py strike <close-out.md> <id>") == 1
        assert f"The spec repo is {r.spec_root}." in prompt
        assert "a fold into another slice — goes on" in prompt
        assert "The plan holds" not in prompt
        assert f"Write your verdict to {slice_dir / 'wrap_up_result.json'}." \
            in prompt
        # gated: the sibling with a whole-repo phase's gate, the primary with
        # the doc gate on the wrap-up branch — once; the gate stage took it
        assert r.wrap_gate_calls == [(["kc", "project", "test"], str(sib))]
        assert r.doc_gate_calls == [True]
        # landed: the doc branch moved up and landed, the sibling's base
        # fast-forwarded and pushed with the doc phase's siblings
        assert g.refs[str(repo)]["main"] == "w1"
        assert g.refs[str(sib)]["main"] == "sw1"
        assert pushes(r) == [(str(repo), "main"), (str(sib), "main")]
        state = load_state(slice_dir)
        wu = state["wrap_up"]
        assert (wu["outcome"], wu["entries"], wu["session"]) == \
            ("landed", ["B1"], "sess-wrap-1")
        assert wu["repos"] == {
            str(repo): {"branch": WRAP, "base": "d0", "head": "w1"},
            str(sib): {"branch": WRAP, "base": "s0", "head": "sw1"}}
        assert wu["store"] == "spec1"
        assert g.specs_commits[0] == \
            "slice 074: close-out report before the wrap-up"
        rows = [h for h in state["history"]
                if h["role"] in ("wrap-up", "wrap-up-gate")]
        assert [(h["role"], h["outcome"]) for h in rows] == \
            [("wrap-up", "done"), ("wrap-up-gate", "green")]
        assert rows[0]["fixed"] == ["B1"] and rows[0]["left"] == []
        assert rows[0]["words"] == ["P2"]
        assert "unknown_key" not in rows[0]
        assert rows[0]["session"] == "sess-wrap-1" and rows[0]["transcript"]
        assert rows[1]["repo"] == str(sib)
        # rendered and committed after it, with the strike
        report = load_report(slice_dir)
        assert "### ~~B1 — a page reads wrong~~" in report
        assert "slice 074: close-out report after the wrap-up" \
            in g.specs_commits
        assert "doc phase done · wrap-up landed" in " ".join(report.split())
        assert state["doc_phase"]["stage"] == "done"


def left_out_run(tmp, step, reason, outcome, **kw):
    """A slice with a sibling whose wrap-up is left out: `step(repo, sib)`
    is the wrap-up's script step. Checks what every soft failure leaves —
    exit 0, no wrap-up commit on any base or the doc branch, the store as
    the wrap-up found it, the event in the record, the outcome and its
    reason, the history row — and returns the loop and the slice."""
    slice_dir, repo, sib = sibling_phase_slice(tmp)
    plant_waiting(slice_dir)
    r = ScriptedLoop(slice_dir, wrap_script(repo, sib), repo_root=repo,
                     wrap_ups=[step(repo, sib)], **kw)
    r._nudge = lambda *a, **k: None
    assert run_to_exit(r) == 0
    g = r.fake_git
    assert g.refs[str(repo)]["main"] == "d0"
    assert g.refs[str(sib)]["main"] == "s0"
    assert pushes(r) == [(str(repo), "main")]
    # the branches stay, unmerged
    assert g.refs[str(sib)].get(WRAP) in ("sw1", "s0")
    # the store as the wrap-up found it, the one event beside it
    store = json.loads((slice_dir / "close-out.json").read_text())
    [event] = left_out_event(slice_dir)
    assert [e for e in store["entries"] if e["id"] != event["id"]] \
        == r.store_at_dispatch["entries"]
    assert event["headline"].startswith(
        "The wrap-up was left out of the landing: " + reason)
    assert event["consequence"].startswith("none in this run")
    assert f"`{WRAP}` at" in "\n".join(event["body"])
    # in the record, not on the wrap-up's own list
    assert [e["id"] for e, _ in close_out.worklist(slice_dir)] == ["B1"]
    report = load_report(slice_dir)
    assert f"{event['id']} — The wrap-up was left out" in report
    assert "wrap-up left out" in " ".join(report.split())
    state = load_state(slice_dir)
    assert state["wrap_up"]["outcome"] == "left_out"
    assert state["wrap_up"]["reason"].startswith(reason)
    assert [h["outcome"] for h in state["history"]
            if h["role"] == "wrap-up"] == [outcome]
    assert state["run_phase"] == "done"
    assert not (slice_dir / "bailout.json").exists()
    return r, slice_dir, repo, sib


def test_a_wrap_up_that_times_out_is_left_out():
    with tempfile.TemporaryDirectory() as tmp:
        left_out_run(tmp, lambda repo, sib: (TIMED_OUT,
                                             wrap_up_fixes(repo, sib)),
                     "the session timed out after 7200s", "timeout")
    # a verdict written before the wedge is not taken: a timeout is a timeout
    with tempfile.TemporaryDirectory() as tmp:
        left_out_run(tmp, lambda repo, sib: ((TIMED_OUT, WRAP_DONE),
                                             wrap_up_fixes(repo, sib)),
                     "the session timed out", "timeout")


def test_a_wrap_up_without_a_verdict_is_left_out_without_a_nudge():
    with tempfile.TemporaryDirectory() as tmp:
        r, *_ = left_out_run(
            tmp, lambda repo, sib: ("done, I think",
                                    wrap_up_fixes(repo, sib)),
            "it wrote no verdict", "invalid")
        assert len(r.wrap_up_sessions) == 1


def test_a_wrap_up_with_an_invalid_verdict_is_left_out():
    with tempfile.TemporaryDirectory() as tmp:
        left_out_run(tmp, lambda repo, sib: (
            {"outcome": "question", "summary": "?"}, wrap_up_fixes(repo, sib)),
            "its verdict is invalid (outcome 'question')", "invalid")


def test_a_blocked_wrap_up_is_left_out():
    with tempfile.TemporaryDirectory() as tmp:
        left_out_run(tmp, lambda repo, sib: (
            {"outcome": "blocked", "summary": "the gate cannot run"},
            wrap_up_fixes(repo, sib)),
            "it answered blocked: the gate cannot run", "blocked")


def test_a_wrap_up_that_leaves_changes_uncommitted_is_left_out():
    def dirt(loop):
        loop.fake_git.dirty_roots[str(loop.sib)] = " M chart.yaml"

    with tempfile.TemporaryDirectory() as tmp:
        def step(repo, sib):
            def effect(loop):
                loop.sib = sib
                wrap_up_fixes(repo, sib, then=dirt)(loop)
            return WRAP_DONE, effect
        r, slice_dir, repo, sib = left_out_run(
            tmp, step, "it left uncommitted changes in Sibling (discarded on "
                       f"{WRAP})", "done")
        # discarded where it left them, tracked and untracked
        assert [c for root, c in r.fake_git.calls
                if str(root) == str(sib) and c[0] == "clean"]
        assert r.fake_git.dirty_roots[str(sib)] == ""


def test_a_wrap_up_that_commits_outside_its_branches_is_left_out():
    with tempfile.TemporaryDirectory() as tmp:
        def step(repo, sib):
            def outside(loop):
                loop.fake_git.commit_on(repo, DOCS, "stray1")
            return WRAP_DONE, wrap_up_fixes(repo, sib, then=outside)
        r, *_ = left_out_run(
            tmp, step, f"it committed outside its branches ({DOCS} in repo "
                       "moved to stray1)", "done")
        # the doc branch put back before the doc phase landed it
        assert "stray1" not in r.fake_git.refs[str(Path(tmp) / "repo")].values()


def test_a_red_sibling_gate_leaves_the_whole_wrap_up_out():
    with tempfile.TemporaryDirectory() as tmp:
        r, *_ = left_out_run(
            tmp, lambda repo, sib: (WRAP_DONE, wrap_up_fixes(repo, sib)),
            "the gate in Sibling is red with its commits", "done",
            wrap_gates=[False])
        # the primary's doc gate never ran on the wrap-up branch; the doc
        # phase's own gate ran on the doc branch
        assert r.doc_gate_calls == [True]
        rows = [h for h in load_state(r.slice_dir)["history"]
                if h["role"] == "wrap-up-gate"]
        assert [h["outcome"] for h in rows] == ["red"]


def test_a_primary_gate_red_with_its_commits_and_green_without():
    with tempfile.TemporaryDirectory() as tmp:
        r, *_ = left_out_run(
            tmp, lambda repo, sib: (WRAP_DONE, wrap_up_fixes(repo, sib)),
            "the doc gate is red with its commits and green without them",
            "done", doc_gates=[False, True])
        # the sibling's gate was green, and its commits are left out too;
        # the doc phase went on from the green without them
        assert r.wrap_gate_calls
        assert r.doc_gate_calls == [False, True]


def test_a_primary_gate_red_with_and_without_goes_to_the_writers_nudge():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo, sib = sibling_phase_slice(tmp)
        plant_waiting(slice_dir)
        r = ScriptedLoop(slice_dir, wrap_script(repo, sib), repo_root=repo,
                         wrap_ups=[(WRAP_DONE, wrap_up_fixes(repo, sib))],
                         doc_gates=[False, False, True])
        nudges = []
        r._nudge = lambda prompt, cwd, sid, label, role: nudges.append(
            (sid, role, prompt))
        assert run_to_exit(r) == 0
        # red on the wrap-up branch, red on the doc branch without it: that
        # red is the doc phase's, nudged to the writer, then green
        assert r.doc_gate_calls == [False, False, True]
        assert [(sid, role) for sid, role, _ in nudges] == \
            [("sess-test", "doc-writer")]
        assert "doc_gate_r2.log" in nudges[0][2]
        assert r.fake_git.refs[str(repo)]["main"] == "d0"
        assert r.fake_git.refs[str(sib)]["main"] == "s0"
        wu = load_state(slice_dir)["wrap_up"]
        assert wu["outcome"] == "left_out"
        assert wu["reason"].startswith("the doc gate is red with its commits "
                                       "and without them")


def test_a_project_without_a_doc_phase_runs_the_wrap_up_and_lands_it():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp, config=rc(doc=False))
        plant_waiting(slice_dir)
        script = [V["exec_done"], V["review_signoff"], V["consult_complete"],
                  ("test-agent", {"outcome": "clean", "summary": "ok"},
                   lambda loop: model_repos(loop, repo, docs=False))]
        r = ScriptedLoop(slice_dir, script, repo_root=repo,
                         wrap_ups=[(WRAP_DONE, wrap_up_fixes(repo))])
        assert run_to_exit(r) == 0
        assert not [role for role, *_ in r.spawned if role == "doc-writer"]
        g = r.fake_git
        assert (str(repo), ("checkout", "-b", WRAP, "m0")) in [
            (str(root), c) for root, c in g.calls]
        assert r.doc_gate_calls == [True]
        assert g.refs[str(repo)]["main"] == "w1"
        assert (str(repo), "main") in pushes(r)
        state = load_state(slice_dir)
        assert state["doc_phase"]["writer"] is False
        assert state["doc_phase"]["stage"] == "done"
        assert state["wrap_up"]["outcome"] == "landed"
        assert state["run_phase"] == "done"
        report = " ".join(load_report(slice_dir).split())
        header = report[report.index("Run:"):report.index("## ")]
        assert "wrap-up landed" in header and "doc phase" not in header


def test_without_a_doc_phase_a_left_out_wrap_up_lands_nothing():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp, config=rc(doc=False))
        plant_waiting(slice_dir)
        script = [V["exec_done"], V["review_signoff"], V["consult_complete"],
                  ("test-agent", {"outcome": "clean", "summary": "ok"},
                   lambda loop: model_repos(loop, repo, docs=False))]
        r = ScriptedLoop(slice_dir, script, repo_root=repo,
                         wrap_ups=[({"outcome": "blocked", "summary": "no"},
                                    wrap_up_fixes(repo))])
        assert run_to_exit(r) == 0
        assert r.doc_gate_calls == []
        assert r.fake_git.refs[str(repo)]["main"] == "m0"
        assert DOCS not in r.fake_git.refs[str(repo)]
        assert not pushes(r)
        assert load_state(slice_dir)["doc_phase"]["stage"] == "done"
    # red with its commits and without them: this project runs no doc gate,
    # so without the wrap-up the run would have completed over that red —
    # and the wrap-up is never the reason it does not
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp, config=rc(doc=False))
        plant_waiting(slice_dir)
        script = [V["exec_done"], V["review_signoff"], V["consult_complete"],
                  ("test-agent", {"outcome": "clean", "summary": "ok"},
                   lambda loop: model_repos(loop, repo, docs=False))]
        r = ScriptedLoop(slice_dir, script, repo_root=repo,
                         wrap_ups=[(WRAP_DONE, wrap_up_fixes(repo))],
                         doc_gates=[False, False])
        assert run_to_exit(r) == 0
        assert not (slice_dir / "bailout.json").exists()
        assert r.doc_gate_calls == [False, False]
        assert r.fake_git.refs[str(repo)]["main"] == "m0"
        assert not pushes(r)
        state = load_state(slice_dir)
        assert state["wrap_up"]["outcome"] == "left_out"
        assert "red with its commits and without them" in state["wrap_up"]["reason"]
        assert state["doc_phase"]["stage"] == "done"
        assert "gate_last" not in state["doc_phase"]


def test_a_held_repo_gets_no_wrap_up_branch_and_is_named_in_the_prompt():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo, sib = held_sibling_slice(tmp)
        plant_waiting(slice_dir)
        r = ScriptedLoop(slice_dir, wrap_script(repo, sib), repo_root=repo,
                         wrap_ups=[(WRAP_DONE, wrap_up_fixes(repo))])
        assert run_to_exit(r) == 0
        assert not [c for root, c in r.fake_git.calls
                    if str(root) == str(sib) and c[:3] == ("checkout", "-b",
                                                           WRAP)]
        prompt = r.wrap_up_sessions[0]["prompt"]
        assert ("- The plan holds these repos (`## Push holds`): they are not "
                "yours to\n  change, and the driver cut no branch in them:\n"
                "  - ../Sibling — a push deploys dev and prd together\n") \
            in prompt
        assert "yours to push" not in prompt
        assert f"  - {sib} — branch" not in prompt
        assert list(load_state(slice_dir)["wrap_up"]["repos"]) == [str(repo)]
        assert r.fake_git.refs[str(repo)]["main"] == "w1"


def test_a_resume_into_the_wrap_up_starts_it_again_from_a_clean_slate():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo, sib = sibling_phase_slice(tmp)
        plant_waiting(slice_dir)

        def interrupted(loop):
            loop.fake_git.dirty_roots[str(repo)] = " M half-done.py"
            raise KeyboardInterrupt

        r = ScriptedLoop(slice_dir, wrap_script(repo, sib), repo_root=repo,
                         wrap_ups=[(WRAP_DONE, wrap_up_fixes(
                             repo, sib, then=interrupted))])
        assert run_to_exit(r) == 130
        state = load_state(slice_dir)
        assert state["doc_phase"]["stage"] == "wrap-up"
        assert state["wrap_up"]["store"] == "spec1"
        assert not close_out.worklist(slice_dir), "the attempt struck B1"

        r2 = ScriptedLoop(slice_dir, [], resume=True, repo_root=repo,
                          wrap_ups=[(WRAP_DONE, wrap_up_fixes(repo, sib))])
        for name in ("refs", "parents", "branch_at", "dirty_roots",
                     "spec_head", "specs_committed", "spec_snapshots"):
            setattr(r2.fake_git, name, getattr(r.fake_git, name))
        r2.fake_git.parents.pop("w1")
        r2.fake_git.parents.pop("sw1")
        assert run_to_exit(r2) == 0
        g = r2.fake_git
        calls = [(str(root), c) for root, c in g.calls]
        # the tree it left put back, its changes discarded, its branches
        # deleted before they are cut again
        first_cut = calls.index((str(repo), ("checkout", "-b", WRAP, "d0")))
        assert calls.index((str(repo), ("clean", "-fd"))) < first_cut
        assert calls.index((str(repo), ("branch", "-D", WRAP))) < first_cut
        assert calls.index((str(sib), ("branch", "-D", WRAP))) < first_cut
        # the store back to where it stood: B1 waits again, and the second
        # dispatch is told so
        assert "B1 · label" in r2.wrap_up_sessions[0]["prompt"]
        assert any("back to where it stood before the wrap-up (spec1)" in m
                   for m in g.specs_commits)
        assert load_state(slice_dir)["wrap_up"]["outcome"] == "landed"
        assert g.refs[str(repo)]["main"] == "w1"


def test_a_resume_past_the_wrap_up_never_dispatches_it():
    for stage in ("gate", "landing", "siblings"):
        with tempfile.TemporaryDirectory() as tmp:
            slice_dir, repo = make_slice(tmp)
            plant_waiting(slice_dir)
            state = {
                "slice": "074_test_slice", "created_at": "t",
                "orchestrator": None, "run_phase": "docs",
                "bases": {str(repo): "main"}, "known_phases": ["1"],
                "phases": {"1": {"status": "merged", "stage": None,
                                 "executor_rounds": 1, "review_rounds": 1,
                                 "gate_runs": 1, "gate_fix_rounds": 0}},
                "generation": 0, "test_rounds": 1, "consult_seq": 1,
                "in_flight": None, "history": [],
                "doc_phase": {"stage": stage, "gate_runs": 0, "nudges": 0,
                              "session": "sess-old"},
                "wrap_up": {"outcome": "left_out", "reason": "timeout",
                            "session": None, "entries": ["B1"],
                            "store": None, "repos": {}},
            }
            (slice_dir / "state.json").write_text(json.dumps(state))
            r = ScriptedLoop(slice_dir, [], resume=True, repo_root=repo)
            r.fake_git.branches.add(DOCS)
            assert run_to_exit(r) == 0, stage
            assert not r.wrap_up_sessions, stage
            assert close_out.worklist(slice_dir), "B1 still waits"
            assert load_state(slice_dir)["doc_phase"]["stage"] == "done"


def test_the_wrap_up_is_a_required_agent_refused_when_missing():
    assert "wrap-up" in run_loop.REQUIRED_AGENTS
    assert run_loop.MODELS["wrap-up"] == ("opus", "xhigh")
    assert run_loop.TIMEOUTS["wrap-up"] == 7200
    assert run_loop.VERDICTS["wrap-up"] == {"done", "blocked"}
    with tempfile.TemporaryDirectory() as tmp:
        agents = Path(tmp) / "agents"
        agents.mkdir()
        for role in run_loop.REQUIRED_AGENTS:
            if role != "wrap-up":
                (agents / f"{role}.md").write_text("---\nname: x\n---\n")
        loop = RunLoop.__new__(RunLoop)
        err = io.StringIO()
        with patched(run_loop, AGENTS_DIR=agents), \
                contextlib.redirect_stderr(err):
            try:
                loop._assert_agents()
            except SystemExit as e:
                assert e.code == 2
            else:
                raise AssertionError("a missing wrap-up.md must exit 2")
        assert "agent definition(s) not found: wrap-up" in err.getvalue()


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


def test_the_doc_landing_takes_the_devlock_when_there_is_no_test_phase():
    """The lease is taken for the landing's push, not the writing — the doc
    phase rolls dev only when it pushes."""
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
        at_push = watch_push_holder(r, scripts_dir / "dev-holder")
        assert run_to_exit(r) == 0
        assert held == [False]
        # The driver's own settle push is outside the lease; the landing's is
        # under it.
        assert at_push == [False, True]
        assert not (scripts_dir / "dev-holder").exists(), "released at end"


def test_a_repo_with_no_aiworkflowrc_cannot_be_driven():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        (repo / ".aiworkflowrc").unlink()
        r = ScriptedLoop(slice_dir, [], repo_root=repo)
        assert run_to_exit(r) == 2


# A phase that switches `[push] enabled = true` on — every project's first
# deploy slice does — got no push check and a doc landing that pushed nothing,
# primary repo and siblings alike: `cfg` is read once, at the run's start
# (AIWF-80). The driver reads `push.enabled` again at each push point — the
# push check, its own push without a test phase, the doc landing in every
# repo — and nothing else in the config.

def rewrites_rc(config):
    """A script step's effect: the session rewrote the repo's
    `.aiworkflowrc`."""
    def effect(loop):
        (loop.repo_root / ".aiworkflowrc").write_text(config)
    return effect


def test_a_phase_that_switches_push_on_gets_the_push_check_and_a_pushing_landing():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp, config=rc(push=False))
        script = [(*V["exec_done"], rewrites_rc(rc())), V["review_signoff"],
                  V["consult_complete"], V["test_clean"], V["doc_done"]]
        r = ScriptedLoop(slice_dir, script, repo_root=repo)
        r.fake_git.unpushed[str(repo)] = "3"
        nudges = []

        def fake_nudge(prompt, cwd, session_id, label, role):
            nudges.append(prompt)
            r.fake_git.unpushed.clear()   # the nudged session pushes

        r._nudge = fake_nudge
        assert run_to_exit(r) == 0
        assert len(nudges) == 1 and "3 commit(s)" in nudges[0]
        assert ("rebase", "origin/main") in [
            c for _, c in r.fake_git.mutations("rebase")]
        assert pushes(r) == [(str(repo), "main")]


def test_a_phase_that_switches_push_on_gets_its_sibling_doc_commits_pushed():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo, sib = sibling_phase_slice(tmp)
        (repo / ".aiworkflowrc").write_text(rc(push=False))
        script = sibling_doc_script(sib)
        script[0] = (*V["exec_done"], rewrites_rc(rc()))
        r = ScriptedLoop(slice_dir, script, repo_root=repo)
        assert run_to_exit(r) == 0
        assert pushes(r) == [(str(repo), "main"), (str(sib), "main")]
        assert f"pushed main in {sib} (1 commit(s)" \
            in (slice_dir / "log.txt").read_text()


def test_a_phase_that_switches_push_on_without_a_test_phase_gets_the_drivers_push():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(
            tmp, config=rc(test=False, doc=False, push=False))
        script = [(*V["exec_done"], rewrites_rc(rc(test=False, doc=False))),
                  V["review_signoff"], V["consult_complete"]]
        r = ScriptedLoop(slice_dir, script, repo_root=repo)
        assert run_to_exit(r) == 0
        assert pushes(r) == [(str(repo), "main")]


def test_a_phase_that_switches_push_off_lands_the_docs_locally_and_pushes_nothing():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        script = [(*V["exec_done"], rewrites_rc(rc(push=False))),
                  V["review_signoff"], V["consult_complete"],
                  V["test_clean"], V["doc_done"]]
        r = ScriptedLoop(slice_dir, script, repo_root=repo)
        # pushing, this would be nudged and the landing would bail `blocked`
        r.fake_git.unpushed[str(repo)] = "3"
        r._nudge = lambda *a, **kw: (_ for _ in ()).throw(
            AssertionError("a project that stopped pushing is not nudged"))
        assert run_to_exit(r) == 0
        assert ("rebase", "main") in [
            c for _, c in r.fake_git.mutations("rebase")]
        assert pushes(r) == []
        assert "the project does not push — nothing sent to origin" \
            in (slice_dir / "log.txt").read_text()


def test_a_phase_that_breaks_the_config_bails_at_the_push_check_and_resumes():
    """Not the exit 2 a config broken before the run gives: the slice's own
    phase broke it, so fixing the file and resuming is the way out."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        broken = rc() + "[push]\nenable = false\n"
        script = [(*V["exec_done"], rewrites_rc(broken)), V["review_signoff"],
                  V["consult_complete"], V["test_clean"]]
        r = ScriptedLoop(slice_dir, script, repo_root=repo)
        assert run_to_exit(r) == 3
        bail = json.loads((slice_dir / "bailout.json").read_text())
        assert bail["reason"] == "protocol_failure"
        assert "unknown key(s): `enable`" in bail["details"]
        assert "`push.enabled`" in bail["details"]
        assert "fix it, then resume" in bail["details"]
        assert load_state(slice_dir)["run_phase"] == "test"
        assert not any(role == "doc-writer" for role, *_ in r.spawned)
        assert pushes(r) == []

        (repo / ".aiworkflowrc").write_text(rc())
        r2 = ScriptedLoop(slice_dir, [V["test_clean"], V["doc_done"]],
                          resume=True, repo_root=repo)
        assert run_to_exit(r2) == 0
        assert pushes(r2) == [(str(repo), "main")]
        assert load_state(slice_dir)["run_phase"] == "done"


def test_a_phase_that_switches_the_doc_phase_off_still_gets_it():
    """Only `push.enabled` is read again: the rest of the config is the one
    the run started with."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        script = [(*V["exec_done"], rewrites_rc(rc(doc=False))),
                  V["review_signoff"], V["consult_complete"],
                  V["test_clean"], V["doc_done"]]
        r = ScriptedLoop(slice_dir, script, repo_root=repo)
        assert run_to_exit(r) == 0
        assert not r.script
        assert [role for role, *_ in r.spawned][-1] == "doc-writer"


# -- the devlock --------------------------------------------------------------

def watch_push_holder(loop, holder):
    """Wrap the loop's git so every `git push` records whether the devlock's
    holder note was in place at the moment of the push."""
    inner = loop.git
    seen = []

    def watching(*args, **kwargs):
        if args and args[0] == "push":
            seen.append(holder.exists())
        return inner(*args, **kwargs)

    loop.git = watching
    return seen


def test_devlock_held_for_the_test_phase_and_the_doc_landing_only():
    """Two holds, not one hold spanning both phases: the test phase's
    verification, then the landing's push. The doc phase's writing and
    gating — the slow part — run with the lease let go."""
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
        at_push = watch_push_holder(r, scripts_dir / "dev-holder")
        assert run_to_exit(r) == 0
        assert events == [("test", True), ("doc", False)]
        assert at_push == [True], "the landing pushes under the lease"
        assert not (scripts_dir / "dev-holder").exists(), "released at end"
        log = (slice_dir / "log.txt").read_text()
        assert [line.split("devlock ACQUIRED ")[1]
                for line in log.splitlines()
                if "devlock ACQUIRED" in line] == [
                    "(slice 074 test phase)", "(slice 074 doc landing)"]
        assert log.count("devlock released") == 2


def test_a_doc_landing_that_does_not_push_never_takes_the_devlock():
    """No push, no dev roll, nothing to coordinate — the merge is local and
    the lease stays with whoever else wants it."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp, config=rc(push=False, devlock=True))
        scripts_dir = slice_dir.parent.parent / "scripts"
        scripts_dir.mkdir()
        script = [
            V["exec_done"], V["review_signoff"], V["consult_complete"],
            V["test_clean"], V["doc_done"],
        ]
        r = ScriptedLoop(slice_dir, script, repo_root=repo)
        assert run_to_exit(r) == 0
        acquires = [line for line
                    in (slice_dir / "log.txt").read_text().splitlines()
                    if "devlock ACQUIRED" in line]
        assert len(acquires) == 1
        assert acquires[0].endswith("(slice 074 test phase)")
        assert pushes(r) == []


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
        # one sleep to the stated reset, looking for Pilot's halt file
        # every HALT_POLL seconds on the way
        assert 0 < sum(r.sleeps) <= 12 * 3600
        assert max(r.sleeps) <= run_loop.HALT_POLL
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
        # Falsy: a nudge that was not swallowed asks for no recovery.
        r._nudge = lambda prompt, cwd, sid, label, role, **kw: (
            nudges.append(prompt))
        with patched(run_loop, run_kc_session=r.run_kc_session):
            assert run_to_exit(r) == 3
        assert len(nudges) == 1
        assert "verdict" in nudges[0]
        bail = json.loads((slice_dir / "bailout.json").read_text())
        assert bail["reason"] == "blocked"
        assert "missing/unparseable" in bail["details"]


def test_a_swallowed_verdict_nudge_resumes_the_session_to_recover_its_wait():
    """#843 (slice 209): the doc-writer had four survey sub-agents out; the
    fourth's completion landed mid-turn and died with the process, so the
    session ended with no verdict and the first send back into it was eaten
    by the CLI's stopped-task bookkeeping ("No response requested."). That
    no-op is the tell: the session was cut mid-wait, and the verdict nudge's
    "do not start new work" leaves it nothing legal to do. The driver resumes
    it with the recovery prompt instead — under the role's own timeout, so it
    can retrieve the lost report and finish the round."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        script = [
            ("code-writer", "did the work, forgot the verdict"),
            ("code-writer", SWALLOWED),
            ("code-writer", {"outcome": "done",
                             "summary": "recovered the survey, then finished"}),
            V["review_signoff"], *TAIL,
        ]
        r = SpawningLoop(slice_dir, script, repo_root=repo)
        with patched(run_loop, run_kc_session=r.run_kc_session):
            assert run_to_exit(r) == 0
        assert not r.script
        assert not (slice_dir / "bailout.json").exists()
        writer_prompts = [p for role, p in r.session_prompts
                          if role == "code-writer"]
        assert len(writer_prompts) == 3, "the round, the nudge, the recovery"
        assert writer_prompts[1].startswith("Your session ended without")
        assert writer_prompts[2].startswith(
            "Your session ended while it was waiting")
        # The recovery is a resume of the same session, dispatched with the
        # role's own timeout rather than the nudge's short one.
        resumes = [(sid, timeout) for role, sid, timeout in r.session_resumes
                   if role == "code-writer"]
        assert resumes[0] == (None, run_loop.TIMEOUTS["code-writer"])
        assert resumes[1] == ("sess-1", run_loop.NUDGE_TIMEOUT)
        assert resumes[2] == ("sess-1", run_loop.TIMEOUTS["code-writer"])
        state = load_state(slice_dir)
        outcomes = [(h["role"], h["outcome"]) for h in state["history"]]
        assert ("code-writer", "done") in outcomes
        assert ("code-writer", "blocked") not in outcomes
        assert state["phases"]["1"]["status"] == "merged"
        row = next(h for h in state["history"]
                   if (h["role"], h["outcome"]) == ("code-writer", "done"))
        assert isinstance(row["duration_s"], int), (
            "the round is priced with its recovery resume folded in")
        log = (slice_dir / "log.txt").read_text()
        assert "cut mid-wait" in log
        assert "sending it once more" not in log, (
            "the verdict nudge recovers instead of repeating itself")


def test_a_verdict_nudge_answered_with_no_turn_at_all_recovers_the_same_way():
    """Slice 201's shape of the same signal: the swallowed resume produced no
    assistant turn at all, so the response is empty rather than the recovery's
    stock sentence. Empty means the same thing — a session cut mid-wait — and
    buys the same recovery resume."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        script = [
            ("code-writer", "did the work, forgot the verdict"),
            ("code-writer", ""),
            ("code-writer", {"outcome": "done", "summary": "verdict written"}),
            V["review_signoff"], *TAIL,
        ]
        r = SpawningLoop(slice_dir, script, repo_root=repo)
        with patched(run_loop, run_kc_session=r.run_kc_session):
            assert run_to_exit(r) == 0
        assert not r.script
        assert not (slice_dir / "bailout.json").exists()
        writer_prompts = [p for role, p in r.session_prompts
                          if role == "code-writer"]
        assert len(writer_prompts) == 3
        assert writer_prompts[2].startswith(
            "Your session ended while it was waiting")
        assert ("code-writer", "done") in [
            (h["role"], h["outcome"])
            for h in load_state(slice_dir)["history"]]
        assert "cut mid-wait" in (slice_dir / "log.txt").read_text()


def test_a_recovered_session_that_still_writes_nothing_gets_the_nudge_again():
    """A recovery resume owes a verdict like any other session. This one ends
    without one, but its verdict nudge lands (no no-op) and writes it — so the
    round counts on that verdict, one recovery in."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        script = [
            ("code-writer", "did the work, forgot the verdict"),
            ("code-writer", SWALLOWED),                     # → recovery 1
            ("code-writer", "recovered the report, forgot the verdict again"),
            ("code-writer", {"outcome": "done", "summary": "verdict at last"}),
            V["review_signoff"], *TAIL,
        ]
        r = SpawningLoop(slice_dir, script, repo_root=repo)
        with patched(run_loop, run_kc_session=r.run_kc_session):
            assert run_to_exit(r) == 0
        assert not r.script
        assert not (slice_dir / "bailout.json").exists()
        writer_prompts = [p for role, p in r.session_prompts
                          if role == "code-writer"]
        assert len(writer_prompts) == 4, (
            "the round, the nudge, the recovery, the nudge again")
        assert writer_prompts[3] == writer_prompts[1]
        log = (slice_dir / "log.txt").read_text()
        assert log.count("cut mid-wait") == 1
        outcomes = [(h["role"], h["outcome"])
                    for h in load_state(slice_dir)["history"]]
        assert ("code-writer", "done") in outcomes
        assert ("code-writer", "blocked") not in outcomes


def test_mid_wait_recoveries_stop_at_the_cap():
    """LOST_WAIT_CAP recoveries per round, then the nudge falls back to its
    same-prompt retry and the round is the protocol failure it always was.
    The bail says how many recoveries were spent getting there."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        script = [
            ("code-writer", "did the work, forgot the verdict"),
            ("code-writer", SWALLOWED),                  # → recovery 1
            ("code-writer", "resumed, still no verdict"),
            ("code-writer", SWALLOWED),                  # → recovery 2
            ("code-writer", "resumed again, still no verdict"),
            ("code-writer", SWALLOWED),                  # at the cap: retry
            ("code-writer", SWALLOWED),                  # the same prompt
        ]
        r = SpawningLoop(slice_dir, script, repo_root=repo)
        with patched(run_loop, run_kc_session=r.run_kc_session):
            assert run_to_exit(r) == 3
        assert not r.script
        writer_prompts = [p for role, p in r.session_prompts
                          if role == "code-writer"]
        assert len(writer_prompts) == 7
        assert len([p for p in writer_prompts
                    if p.startswith("Your session ended while it was "
                                    "waiting")]) == run_loop.LOST_WAIT_CAP
        assert writer_prompts[6] == writer_prompts[5], "the same prompt again"
        bail = json.loads((slice_dir / "bailout.json").read_text())
        assert bail["reason"] == "blocked"
        assert "missing/unparseable" in bail["details"]
        assert "2 mid-wait recoveries" in bail["details"]
        log = (slice_dir / "log.txt").read_text()
        assert log.count("sending it once more") == 1
        assert log.count("cut mid-wait") == run_loop.LOST_WAIT_CAP


def test_verdict_written_on_the_commit_nudge_is_salvaged():
    """#809: the writer ended rc!=0 with no verdict and a dirty tree. The
    verdict nudge produced nothing, but the commit nudge got the session to
    commit AND write a valid verdict — that verdict is the round's, so the
    phase proceeds instead of bailing on a stale `blocked`."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        script = [
            ("code-writer", "did the work, forgot the verdict", dirties()),
            ("code-writer", "the verdict nudge produced nothing"),
            ("code-writer", {"outcome": "done", "summary": "committed it"},
             commits),
            V["review_signoff"], *TAIL,
        ]
        r = SpawningLoop(slice_dir, script, repo_root=repo)
        with patched(run_loop, run_kc_session=r.run_kc_session):
            assert run_to_exit(r) == 0
        assert not r.script
        assert not (slice_dir / "bailout.json").exists()
        writer_prompts = [p for role, p in r.session_prompts
                          if role == "code-writer"]
        assert len(writer_prompts) == 3, "the round, then exactly two nudges"
        assert writer_prompts[1].startswith("Your session ended without")
        assert writer_prompts[2].startswith("Your session ended leaving")
        assert r.gate_calls, "the phase went on to its gate"
        state = load_state(slice_dir)
        outcomes = [(h["role"], h["outcome"]) for h in state["history"]]
        assert ("code-writer", "done") in outcomes
        assert ("code-writer", "blocked") not in outcomes, (
            "the history row carries the salvaged verdict, not the "
            "driver's protocol-failure ruling")
        assert state["phases"]["1"]["status"] == "merged"
        assert "wrote its verdict on the commit nudge — salvaged" in (
            slice_dir / "log.txt").read_text()


def test_commit_nudge_that_writes_no_verdict_still_counts_blocked():
    """The other half: a commit nudge that cleans the tree and leaves no
    verdict changes nothing — the protocol failure stands."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        script = [
            ("code-writer", "did the work, forgot the verdict", dirties()),
            ("code-writer", "the verdict nudge produced nothing"),
            ("code-writer", "committed, still no verdict", commits),
        ]
        r = SpawningLoop(slice_dir, script, repo_root=repo)
        with patched(run_loop, run_kc_session=r.run_kc_session):
            assert run_to_exit(r) == 3
        assert not r.script
        bail = json.loads((slice_dir / "bailout.json").read_text())
        assert bail["reason"] == "blocked"
        assert "missing/unparseable" in bail["details"]
        state = load_state(slice_dir)
        assert ("code-writer", "blocked") in [
            (h["role"], h["outcome"]) for h in state["history"]]
        assert "salvaged" not in (slice_dir / "log.txt").read_text()


def test_a_swallowed_commit_nudge_is_sent_once_more():
    """The same-prompt retry survives where it belongs: the commit nudge's
    session has already done its work, so a send the harness eats is just an
    ask that never arrived — repeat it. Only the verdict nudge reads the
    no-op as a session cut mid-wait."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        script = [
            ("code-writer", "did the work, forgot the verdict", dirties()),
            ("code-writer", "the verdict nudge produced nothing"),
            ("code-writer", SWALLOWED),          # the commit nudge, eaten
            ("code-writer", {"outcome": "done", "summary": "committed it"},
             commits),
            V["review_signoff"], *TAIL,
        ]
        r = SpawningLoop(slice_dir, script, repo_root=repo)
        with patched(run_loop, run_kc_session=r.run_kc_session):
            assert run_to_exit(r) == 0
        assert not r.script
        assert not (slice_dir / "bailout.json").exists()
        writer_prompts = [p for role, p in r.session_prompts
                          if role == "code-writer"]
        assert len(writer_prompts) == 4
        assert writer_prompts[1].startswith("Your session ended without")
        assert writer_prompts[2].startswith("Your session ended leaving")
        assert writer_prompts[3] == writer_prompts[2], "the same prompt again"
        log = (slice_dir / "log.txt").read_text()
        assert log.count("sending it once more") == 1
        assert "cut mid-wait" not in log
        outcomes = [(h["role"], h["outcome"])
                    for h in load_state(slice_dir)["history"]]
        assert ("code-writer", "done") in outcomes
        assert ("code-writer", "blocked") not in outcomes


def test_doc_writer_verdict_on_the_commit_nudge_is_salvaged():
    """The doc phase's writer takes the same salvage, on
    doc_phase_result.json."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        script = [
            V["exec_done"], V["review_signoff"], V["consult_complete"],
            V["test_clean"],
            ("doc-writer", "wrote the pages, forgot the verdict", dirties()),
            ("doc-writer", "the verdict nudge produced nothing"),
            ("doc-writer", {"outcome": "done", "summary": "docs committed"},
             commits),
        ]
        r = SpawningLoop(slice_dir, script, repo_root=repo)
        with patched(run_loop, run_kc_session=r.run_kc_session):
            assert run_to_exit(r) == 0
        assert not r.script
        assert not (slice_dir / "bailout.json").exists()
        doc_prompts = [p for role, p in r.session_prompts
                       if role == "doc-writer"]
        assert len(doc_prompts) == 3, "the round, then exactly two nudges"
        state = load_state(slice_dir)
        assert state["doc_phase"]["stage"] == "done"
        outcomes = [(h["role"], h["outcome"]) for h in state["history"]]
        assert ("doc-writer", "done") in outcomes
        assert ("doc-writer", "blocked") not in outcomes
        assert "wrote its verdict on the commit nudge — salvaged" in (
            slice_dir / "log.txt").read_text()


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
    server — also passes `--strict-mcp-config` plus the `--mcp-config` naming
    the promoted servers, so it spawns with those and nothing else. Nudges
    carry the resumed role's flags: a prefix that differs from the original's
    misses the cache."""
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
        home = promoted_home(Path(tmp) / "home", FAKE_CLAUDE_JSON)
        with home, patched(run_loop, run_kc_session=r.run_kc_session):
            assert run_to_exit(r) == 0
            by_role = dict(r.session_flags)
            for role in ("code-writer", "code-reviewer", "consult",
                         "doc-writer"):
                assert by_role[role] == [
                    "--disable-slash-commands", "--strict-mcp-config",
                    "--mcp-config", str(home.config_path)], role
            assert by_role["test-agent"] == ["--disable-slash-commands"]
            assert run_loop.spawn_flags(None) == run_loop.spawn_flags("consult")
            assert "--strict-mcp-config" not in run_loop.spawn_flags(
                "test-agent")
    # No promoted server anywhere: the flags are what they were before the
    # promotion existed, and the test-agent's are untouched either way.
    assert run_loop.spawn_flags("code-writer") == ["--disable-slash-commands",
                                                   "--strict-mcp-config"]
    assert run_loop.spawn_flags("test-agent") == ["--disable-slash-commands"]


def test_promoted_mcp_servers_are_copied_by_name():
    """The promoted entries travel verbatim — type, url and, where there is
    one, the header: the bearer token, the worker's `${VAR:-}` left for the
    spawned claude to expand — and nothing else in ~/.claude.json does: not
    the operator's other servers, not the file's other top-level keys, not the
    per-project sections."""
    with tempfile.TemporaryDirectory() as tmp:
        home = promoted_home(Path(tmp) / "home", FAKE_CLAUDE_JSON)
        with home:
            path, notes = run_loop.write_promoted_mcp_config()
            assert path == home.config_path
            assert notes == []
            assert json.loads(path.read_text()) == {"mcpServers": {
                "fieldnotes": {
                    "type": "http", "url": "https://fieldnotes.invalid/mcp",
                    "headers": {"Authorization": "Bearer sekrit-token"}},
                "gitblit": {"type": "http", "url": "http://git/api/mcp/mcp"},
                "kubecoder-worker": {
                    "type": "http", "url": "http://127.0.0.1:44557/mcp",
                    "headers": {
                        "X-Kubecoder-Session-Name": "${KUBECODER_SESSION_NAME:-}"}}}}


def test_a_missing_promoted_server_is_a_note_and_the_rest_still_travel():
    """A home with fieldnotes alone still promotes it: each absent server is
    one logged line, not an error, and the config carries what was there."""
    fieldnotes_only = json.dumps({"mcpServers": {
        "fieldnotes": {"type": "http", "url": "https://fieldnotes.invalid/mcp"},
        "jenkins": {"type": "http", "url": "https://jenkins.invalid/mcp"}}})
    with tempfile.TemporaryDirectory() as tmp:
        with promoted_home(Path(tmp) / "home", fieldnotes_only) as home:
            config, missing = run_loop.promoted_mcp_config()
            assert list(config["mcpServers"]) == ["fieldnotes"]
            assert missing == ["gitblit", "kubecoder-worker"]
            logged = []
            flags = run_loop.spawn_flags("code-writer", logged.append)
            assert flags == ["--disable-slash-commands", "--strict-mcp-config",
                             "--mcp-config", str(home.config_path)]
            assert len(logged) == 2
            assert "gitblit" in logged[0] and "kubecoder-worker" in logged[1]
            assert json.loads(home.config_path.read_text()) == config


def test_the_promoted_config_is_private_and_written_atomically():
    """It carries a bearer token, so it is written 0600 and under the user's
    home, where no repo and no slice folder can pick it up — and by temp file
    plus rename: one home serves the environments running loops concurrently,
    so a write that dies half-way must leave the file a reader is loading
    exactly as it was, and leave no debris beside it."""
    with tempfile.TemporaryDirectory() as tmp:
        with promoted_home(Path(tmp) / "home", FAKE_CLAUDE_JSON) as home:
            path, notes = run_loop.write_promoted_mcp_config()
            assert path == home.config_path and notes == []
            assert stat.S_IMODE(path.stat().st_mode) == 0o600
            assert path.is_relative_to(home.home)
            live = path.read_text()

            class no_space:
                loads = staticmethod(json.loads)

                @staticmethod
                def dump(*_args, **_kw):
                    raise OSError("no space left on device")

            with patched(run_loop, json=no_space):
                failed, notes = run_loop.write_promoted_mcp_config()
            assert failed is None
            assert any("could not write" in note for note in notes)
            assert path.read_text() == live
            assert [p.name for p in path.parent.iterdir()] == [path.name]


def test_the_promoted_token_never_reaches_the_flags():
    """Only the path is passed; the entry — and the token in it — stays in the
    0600 file, so it cannot land on a command line, in log.txt or in
    state.json."""
    with tempfile.TemporaryDirectory() as tmp:
        with promoted_home(Path(tmp) / "home", FAKE_CLAUDE_JSON):
            flags = run_loop.spawn_flags("code-writer")
            assert "sekrit-token" not in " ".join(flags)
            assert "Bearer" not in " ".join(flags)
            assert flags.count("--mcp-config") == 1


def test_the_promoted_flags_are_fixed_for_the_process():
    """A nudge resumes the session a dispatch created and must carry the same
    prefix, so the answer is computed once and cannot move mid-run."""
    with tempfile.TemporaryDirectory() as tmp:
        with promoted_home(Path(tmp) / "home", FAKE_CLAUDE_JSON) as home:
            first = run_loop.spawn_flags("code-writer")
            (home.home / run_loop.USER_CLAUDE_JSON).write_text("{}")
            assert run_loop.spawn_flags("code-writer") == first


def test_an_unreadable_claude_json_promotes_nothing_and_never_fails():
    """A missing file, malformed JSON, a missing `mcpServers` and a promoted
    name that is not there all leave the flags as they were before the
    promotion existed — one log line, no raise. The store being unreachable
    must never cost a slice its run."""
    bare = ["--disable-slash-commands", "--strict-mcp-config"]
    cases = {
        "missing": None,
        "malformed": "{not json at all",
        "no mcpServers": '{"numStartups": 3}',
        "not an object": '{"mcpServers": []}',
        "other servers only": '{"mcpServers": {"jenkins": {"type": "http"}}}',
    }
    for label, content in cases.items():
        with tempfile.TemporaryDirectory() as tmp:
            with promoted_home(Path(tmp) / "home", content) as home:
                config, missing = run_loop.promoted_mcp_config()
                assert config == {"mcpServers": {}}, label
                assert missing == ["fieldnotes", "gitblit",
                                   "kubecoder-worker"], label
                logged = []
                assert run_loop.spawn_flags("code-writer",
                                            logged.append) == bare, label
                assert run_loop.spawn_flags("test-agent") == [
                    "--disable-slash-commands"], label
                assert len(logged) == 3, label
                assert "fieldnotes" in logged[0] and "gitblit" in logged[1], label
                assert "kubecoder-worker" in logged[2], label
                assert not home.config_path.exists(), label


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


def test_a_valid_verdict_counts_when_the_session_exits_nonzero():
    """The timeout salvage's twin (#957): the verdict file is unlinked at
    dispatch, so a valid one on disk is this round's however the session
    ended — a SIGTERM'd worker, a send the harness lost after the turn.
    Ruling it `blocked` threw away a committed round."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        script = [
            ("code-writer", exited_with(143, {"outcome": "done",
                                              "summary": "built, then cut"})),
            ("code-reviewer", {"outcome": "signoff", "summary": "ok"}),
            ("consult", {"outcome": "complete", "summary": "done"}),
            ("test-agent", {"outcome": "clean", "summary": "ok"}),
            ("doc-writer", {"outcome": "done", "summary": "ok"}),
        ]
        r = SpawningLoop(slice_dir, script, repo_root=repo)
        nudges = []
        r._nudge = lambda prompt, cwd, sid, label, role, retry=True: \
            nudges.append(prompt)
        with patched(run_loop, run_kc_session=r.run_kc_session):
            assert run_to_exit(r) == 0
        assert not nudges, "a complete verdict needs no nudge"
        assert not (slice_dir / "bailout.json").exists()
        assert ("code-writer", "done") in [
            (h["role"], h["outcome"])
            for h in load_state(slice_dir)["history"]]
        assert ("session ended rc=143 but had written "
                "executor_result_r1.json — salvaged") \
            in (slice_dir / "log.txt").read_text()


# -- resume / reattach --------------------------------------------------------

def test_resume_reattaches_the_in_flight_session():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        # simulate a crashed run: state.json with an in-flight executor
        state = {
            "slice": "074_test_slice", "created_at": "t",
            "orchestrator": None, "run_phase": "phases",
            "bases": {}, "known_phases": ["1"],
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
        # the reattached round keeps its number: no new round was banked, so
        # the resumed session is asked for the file its own round owns
        assert load_state(slice_dir)["phases"]["1"]["executor_rounds"] == 1
        assert round_ == 1
        prompt = next(p for role, p in r.prompts if role == "code-writer")
        assert "executor_result_r1.json" in prompt


def merged_state(repo, run_phase, **extra):
    """A crashed run whose only phase has landed, stopped in `run_phase`."""
    state = {
        "slice": "074_test_slice", "created_at": "t", "orchestrator": None,
        "run_phase": run_phase, "bases": {str(repo): "main"},
        "known_phases": ["1"],
        "phases": {"1": {"status": "merged", "stage": None, "branch": None,
                         "target": PROJECT, "executor_rounds": 1,
                         "gate_fix_rounds": 0, "review_rounds": 1,
                         "gate_runs": 1, "gate_green_commit": "abc123",
                         "gate_green_log": "x", "reviewed_head": "abc123"}},
        "generation": 0, "test_rounds": 0, "consult_seq": 1,
        "in_flight": None, "history": [],
    }
    state.update(extra)
    return state


def test_resume_salvages_a_test_phase_verdict_the_hung_round_had_written():
    """#957: the test agent wrote `clean`, and `kc session send` hung after
    the turn had ended. The verdict on disk is that round's — a resume reads
    it rather than paying for the whole verification a second time."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(
            tmp, phases=[("1", "First", PROJECT, True)])
        verdict_path = slice_dir / "test_phase_result_r1.json"
        verdict_path.write_text('{"outcome": "clean", "summary": "verified"}')
        state = merged_state(repo, "test", test_rounds=1)
        state["in_flight"] = {
            "phase": None, "role": "test-agent", "round": 1,
            "verdict_path": str(verdict_path), "session": None,
            "started_at": "t"}
        (slice_dir / "state.json").write_text(json.dumps(state))
        r = SpawningLoop(slice_dir, [V["doc_done"]], resume=True,
                         repo_root=repo)
        with patched(run_loop, run_kc_session=r.run_kc_session):
            assert run_to_exit(r) == 0
        assert [s[0] for s in r.sessions] == ["doc-writer"], (
            "the finished test round was dispatched again")
        state = load_state(slice_dir)
        assert state["test_rounds"] == 1
        assert ("test-agent", 1, "clean", None) in [
            (h["role"], h["round"], h["outcome"], h["session"])
            for h in state["history"]]
        assert "salvaged, no session dispatched" \
            in (slice_dir / "log.txt").read_text()


def test_resume_salvages_an_executor_verdict_the_hung_round_had_written():
    """The same hang one round earlier: the writer had committed and written
    `done`, so the resume reviews that work instead of rebuilding it."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        outputs = slice_dir / "phases" / "P1"
        outputs.mkdir(parents=True)
        verdict_path = outputs / "executor_result_r1.json"
        verdict_path.write_text('{"outcome": "done", "summary": "built"}')
        state = resume_state(PROJECT, stage="executor")
        state["in_flight"] = {
            "phase": "1", "role": "code-writer", "round": 1,
            "verdict_path": str(verdict_path), "session": "sess-hung",
            "started_at": "t"}
        (slice_dir / "state.json").write_text(json.dumps(state))
        script = [("code-reviewer", {"outcome": "signoff", "summary": "ok"}),
                  ("consult", {"outcome": "complete", "summary": "done"}),
                  ("test-agent", {"outcome": "clean", "summary": "ok"}),
                  ("doc-writer", {"outcome": "done", "summary": "ok"})]
        r = SpawningLoop(slice_dir, script, resume=True, repo_root=repo)
        r.fake_git.branches.add("phase/074-P1")
        with patched(run_loop, run_kc_session=r.run_kc_session):
            assert run_to_exit(r) == 0
        assert r.sessions[0][0] == "code-reviewer"
        state = load_state(slice_dir)
        assert state["phases"]["1"]["executor_rounds"] == 1
        row = next(h for h in state["history"] if h["role"] == "code-writer")
        assert (row["round"], row["outcome"], row["session"]) \
            == (1, "done", "sess-hung")


def test_a_test_phase_reattach_keeps_its_round():
    """No verdict on disk, so the crashed session is reattached rather than
    salvaged — as round 1, which is the file that session was told to
    write."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(
            tmp, phases=[("1", "First", PROJECT, True)])
        state = merged_state(repo, "test", test_rounds=1)
        state["in_flight"] = {
            "phase": None, "role": "test-agent", "round": 1,
            "verdict_path": str(slice_dir / "test_phase_result_r1.json"),
            "session": "sess-crashed", "started_at": "t"}
        (slice_dir / "state.json").write_text(json.dumps(state))
        r = SpawningLoop(slice_dir,
                         [("test-agent", {"outcome": "clean",
                                          "summary": "ok"}), V["doc_done"]],
                         resume=True, repo_root=repo)
        with patched(run_loop, run_kc_session=r.run_kc_session):
            assert run_to_exit(r) == 0
        assert ("test-agent", "sess-crashed",
                run_loop.TIMEOUTS["test-agent"]) in r.session_resumes
        state = load_state(slice_dir)
        assert state["test_rounds"] == 1
        assert next(h for h in state["history"]
                    if h["role"] == "test-agent")["round"] == 1


def test_a_reattached_gate_fix_round_keeps_its_numbers():
    """A resume at stage `gate` re-runs the gate first, so an interrupted fix
    round arrives here again — both its counters were banked before the
    crash, and re-banking them spends the cap twice."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        state = resume_state(PROJECT, stage="gate")
        state["phases"]["1"].update(executor_rounds=2, gate_fix_rounds=1)
        state["in_flight"] = {
            "phase": "1", "role": "code-writer", "round": 2,
            "verdict_path": str(slice_dir / "phases" / "P1"
                                / "executor_result_r2.json"),
            "session": "sess-crashed", "started_at": "t"}
        (slice_dir / "state.json").write_text(json.dumps(state))
        r = ScriptedLoop(slice_dir,
                         [V["exec_done"], V["review_signoff"], *TAIL],
                         resume=True, repo_root=repo, gates=[False, True])
        r.fake_git.branches.add("phase/074-P1")
        assert run_to_exit(r) == 0
        role, _, round_, _, resumed = r.spawned[0]
        assert (role, round_, resumed) == ("code-writer", 2, "sess-crashed")
        ps = load_state(slice_dir)["phases"]["1"]
        assert (ps["executor_rounds"], ps["gate_fix_rounds"]) == (2, 1)


def test_resume_at_docs_skips_consult_and_test():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(
            tmp, phases=[("1", "First", PROJECT, True)])
        state = {
            "slice": "074_test_slice", "created_at": "t",
            "orchestrator": None, "run_phase": "docs",
            "bases": {str(repo): "main"},
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


def test_a_bail_leaves_run_phase_at_its_stage_and_resume_reenters_it():
    """Slice 209's second cost: the doc phase bailed, and the resume replayed
    the whole phases → consult → test ladder (a second full test phase) before
    reaching the doc writer again. `run_phase` is left where the run stopped,
    so `--resume` re-enters that stage — what the contract always promised."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        script = [
            V["exec_done"], V["review_signoff"], V["consult_complete"],
            V["test_clean"],
            ("doc-writer", {"outcome": "blocked",
                            "summary": "a survey never came back"}),
        ]
        r1 = ScriptedLoop(slice_dir, script, repo_root=repo)
        assert run_to_exit(r1) == 3
        assert not r1.script
        state = load_state(slice_dir)
        assert state["run_phase"] == "docs", (
            "the stage the run stopped in, not `bailed`")
        assert len(state["bailouts"]) == 1
        assert json.loads((slice_dir / "bailout.json").read_text())["reason"] \
            == "blocked"

        r2 = ScriptedLoop(slice_dir, [V["doc_done"]], resume=True,
                          repo_root=repo)
        assert run_to_exit(r2) == 0
        assert [role for role, *_ in r2.spawned] == ["doc-writer"], (
            "no consult, no second test phase")
        assert load_state(slice_dir)["run_phase"] == "done"


def test_a_bail_in_the_test_stage_resumes_into_the_test_phase():
    """The same re-entry one stage earlier: a test-phase bail resumes into the
    test phase, skipping the completion consult it already answered."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        script = [
            V["exec_done"], V["review_signoff"], V["consult_complete"],
            ("test-agent", {"outcome": "blocked", "summary": "no cluster"}),
        ]
        r1 = ScriptedLoop(slice_dir, script, repo_root=repo)
        assert run_to_exit(r1) == 3
        assert load_state(slice_dir)["run_phase"] == "test"

        r2 = ScriptedLoop(slice_dir, [V["test_clean"], V["doc_done"]],
                          resume=True, repo_root=repo)
        assert run_to_exit(r2) == 0
        assert [role for role, *_ in r2.spawned] == ["test-agent",
                                                     "doc-writer"]


def test_status_says_a_run_bailed():
    """bailout.json is unlinked at every run's start, so one present means
    this run stopped in the stage run_phase names."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        script = [
            V["exec_done"], V["review_signoff"], V["consult_complete"],
            ("test-agent", {"outcome": "blocked", "summary": "no cluster"}),
        ]
        r = ScriptedLoop(slice_dir, script, repo_root=repo)
        assert run_to_exit(r) == 3

        class Args:
            pass

        args = Args()
        args.slice_dir = str(slice_dir)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            run_loop.cmd_status(args)
        assert "run_phase=test (bailed)" in out.getvalue()
        (slice_dir / "bailout.json").unlink()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            run_loop.cmd_status(args)
        assert "run_phase=test  " in out.getvalue()
        assert "(bailed)" not in out.getvalue()


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
    dispatch appends them as given — after the env vars, nothing in between,
    and a flag that takes a value keeps its value in the next argv slot
    (`--mcp-config <path>`, not one joined word)."""
    with tempfile.TemporaryDirectory() as tmp:
        with promoted_home(Path(tmp) / "home", FAKE_CLAUDE_JSON) as home:
            args = _create_args(extra_env={"A": "1"},
                                flags=run_loop.spawn_flags("code-writer"))
            i = args.index("-e")
            assert args[i:] == ["-e", "A=1", "--disable-slash-commands",
                                "--strict-mcp-config", "--mcp-config",
                                str(home.config_path)]
            assert "--mcp-config" not in _create_args(
                flags=run_loop.spawn_flags("test-agent"))
    args = _create_args(extra_env={"A": "1"},
                        flags=run_loop.spawn_flags("code-writer"))
    assert args[args.index("-e"):] == ["-e", "A=1", "--disable-slash-commands",
                                       "--strict-mcp-config"]
    assert "--strict-mcp-config" not in _create_args(
        flags=run_loop.spawn_flags("test-agent"))
    assert "--disable-slash-commands" not in _create_args()


def test_the_session_id_is_learned_during_the_turn():
    """#957: the id used to be read only after the send returned, so a send
    that hung once the turn was over left the round with no session to
    reattach. The engine reports it from the turn's first stream event, so
    the driver polls for it while the send runs — and hears it once."""
    ids = [None, "sess-mid"]
    reported = []
    ticks = []

    class Created:
        returncode, stdout, stderr = 0, "headless-1\n", ""

    class FakeSubprocess:
        @staticmethod
        def run(args, **_):
            return Created()

    def fake_send(name, prompt, cwd, timeout, progress, tick=None):
        for _ in range(3):
            tick()
            ticks.append(list(reported))
        return 0, "the turn's text"

    with patched(run_loop, subprocess=FakeSubprocess, _kc_send=fake_send,
                 _kc_session_id=lambda name, cwd: ids.pop(0) if ids
                 else "sess-mid", SESSION_ID_POLL=0):
        returncode, result = run_loop.run_kc_session(
            "prompt", "/tmp", 60, on_session=reported.append)
    assert returncode == 0
    assert reported == ["sess-mid"], "reported once, and only once"
    assert ticks == [[], ["sess-mid"], ["sess-mid"]], (
        "the id reached on_session before the send returned")
    assert result.session_id == "sess-mid"


def _sent_prompt(**kwargs) -> str:
    """Run run_kc_session against a created session and return the prompt
    it handed `kc session send`."""
    sent = []

    class Created:
        returncode, stdout, stderr = 0, "headless-1\n", ""

    class FakeSubprocess:
        @staticmethod
        def run(args, **_):
            return Created()

    def fake_send(name, prompt, cwd, timeout, progress, tick=None):
        sent.append(prompt)
        return 0, ""

    with patched(run_loop, subprocess=FakeSubprocess, _kc_send=fake_send,
                 _kc_session_id=lambda name, cwd: None):
        run_loop.run_kc_session("the role's prompt", "/tmp", 60, **kwargs)
    assert len(sent) == 1
    return sent[0]


def test_a_fresh_session_opens_with_the_headless_wait_line():
    """AIWF-102: a role is a headless session of its own, so a command it
    backgrounds re-invokes it — the first prompt says so, ahead of the
    role's own, for an agent role and a consult alike."""
    expected = f"{run_loop.HEADLESS_WAIT_LINE}\n\nthe role's prompt"
    assert _sent_prompt(agent="code-writer") == expected
    assert _sent_prompt() == expected


def test_a_resumed_session_is_sent_its_prompt_as_given():
    """A resumed session's history already holds the line: a nudge or a
    reattach goes as written."""
    assert _sent_prompt(resume_session="sess-1",
                        agent="code-writer") == "the role's prompt"


# -- dry run ------------------------------------------------------------------

def dry_run_repo(tmp):
    """The code repo a dry run resolves in — one with a kc manifest, as the
    repo a slice runs from always has."""
    root = Path(tmp) / "repo"
    (root / ".kubecoder").mkdir(parents=True)
    (root / ".kubecoder" / "project.yaml").write_text("projects: {}\n")
    return root


def test_dry_run_lists_phases_and_validates_targets(capsys=None):
    with tempfile.TemporaryDirectory() as tmp:
        sib = make_sibling(tmp)
        root = dry_run_repo(tmp)
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
        # nothing written: no state.json, so no `target_roots` either
        assert not (slice_dir / "state.json").exists()


def test_dry_run_flags_bad_targets():
    with tempfile.TemporaryDirectory() as tmp:
        root = dry_run_repo(tmp)
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
        root = dry_run_repo(tmp)
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
        root = dry_run_repo(tmp)
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


def test_a_dry_run_gates_a_manifest_less_repo_from_the_phase_that_adds_one():
    """`Creates:` on a phase of a repo with no manifest is the phase writing
    it, and the gate is read at gate time: that phase and every later one in
    the repo print the gate they will run. A DONE claimer, or one after the
    phase, gates nothing (AIWF-77)."""
    with tempfile.TemporaryDirectory() as tmp:
        make_sibling(tmp, manifest=False)
        make_sibling(tmp, name="Bare", manifest=False)
        slice_dir, _ = make_slice(tmp, repo=False)
        (slice_dir / "plan.md").write_text(
            "# plan\n\n"
            + phase_section("1", "Stood up", "../Bare", done=True,
                            body="Creates: root\n")
            + "\n" + phase_section("2", "Bootstrap", "../Sibling",
                                   body="Creates: root\n")
            + "\n" + phase_section("3", "Build on it", "../Sibling")
            + "\n" + phase_section("4", "Before its claim", "../Bare")
            + "\n" + phase_section("5", "Late claim", "../Bare",
                                   body="Creates: root\n"))
        code, out, err = dry_run_from(RunLoop(slice_dir, resume=False),
                                      dry_run_repo(tmp))
    assert code == 0, err
    gates = [ln.split("gate: ", 1)[1] for ln in out.splitlines()
             if "gate: " in ln]
    assert gates == [
        "kc project test (gated once P2 adds the manifest)",
        "kc project test (gated once P2 adds the manifest)",
        "(no deterministic gate)",
        "kc project test (gated once P5 adds the manifest)",
    ]


# /dev:plan-slice leaves its session in the spec repo, and a dry run from
# there asked kc about a repo with no manifest: a warning, then every
# component Target of a valid plan reported as a plan problem (AIWF-9).

def code_repo(tmp, name="code", spec_repo="../specs"):
    """A code repo beside make_slice's spec tree — a checkout with a kc
    manifest whose `.aiworkflowrc` names `spec_repo`."""
    root = Path(tmp) / name
    (root / ".git").mkdir(parents=True)
    (root / ".kubecoder").mkdir()
    (root / ".kubecoder" / "project.yaml").write_text("projects: {}\n")
    (root / ".aiworkflowrc").write_text(
        rc().replace('"../specs"', f'"{spec_repo}"'))
    return root


def dry_run_from(loop, repo_root):
    """(exit code, stdout, stderr) of a dry run started in `repo_root`."""
    loop.repo_root = Path(repo_root)
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            run_loop.cmd_dry_run(loop)
        except SystemExit as e:
            return e.code, out.getvalue(), err.getvalue()
    return 0, out.getvalue(), err.getvalue()


def test_a_dry_run_from_the_spec_repo_resolves_in_its_code_repo():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, _ = make_slice(tmp, repo=False)
        code = code_repo(tmp)
        code_repo(tmp, name="elsewhere", spec_repo="../otherspecs")
        unconfigured = code_repo(tmp, name="unconfigured")
        (unconfigured / ".aiworkflowrc").write_text("not = [toml\n")
        loop = RunLoop(slice_dir, resume=False)
        rc_, out, err = dry_run_from(loop, Path(tmp) / "specs")
        assert rc_ == 0, err
        assert f"targets resolve in {code}:" in out
        assert f"target={PROJECT} [project]  root={code}" in out
        assert loop.repo_root == code


def test_a_dry_run_that_finds_no_code_repo_stops_with_the_one_instruction():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, _ = make_slice(tmp, repo=False, phases=[
            ("1", "First"), ("2", "Second", "other")])
        code_repo(tmp, name="elsewhere", spec_repo="../otherspecs")
        rc_, out, err = dry_run_from(RunLoop(slice_dir, resume=False),
                                     Path(tmp) / "specs")
        assert rc_ == 2
        assert "run from the code repo that holds .kubecoder/project.yaml" \
            in err
        assert "no code repo beside" in err
        assert "INVALID" not in out and "plan problems" not in err


def test_a_dry_run_whose_spec_repo_serves_two_code_repos_names_both():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, _ = make_slice(tmp, repo=False)
        one, two = code_repo(tmp, name="one"), code_repo(tmp, name="two")
        rc_, out, err = dry_run_from(RunLoop(slice_dir, resume=False),
                                     Path(tmp) / "specs")
        assert rc_ == 2
        assert "run from the code repo that holds .kubecoder/project.yaml" \
            in err
        assert str(one) in err and str(two) in err
        assert "INVALID" not in out


# -- open pre-run actions ---------------------------------------------------

PRERUN = "Before /dev:run-slice: push the toolchain commits, then kc env restart"
AFTER_RUN = "Push HelmCharts by hand when its hold lifts"


def report_with_actions(slice_dir, *headlines):
    """A close-out report whose actions hold `headlines` as A1, A2, … — live,
    as the plan loop leaves them."""
    close_out.init_report(slice_dir)
    for h in headlines:
        close_out.append_entry(slice_dir, "action", h, "body", consequence="x")


def test_an_open_pre_run_action_refuses_the_run_until_struck():
    """Slice 027's P1 writer was dispatched while its `Before /dev:run-slice`
    action was live and came back blocked on the tool it would have
    provided. The run stops before any dispatch — an operator question —
    and a resume with the entry still live stops again."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        report_with_actions(slice_dir, AFTER_RUN, PRERUN)
        r = ScriptedLoop(slice_dir, [], repo_root=repo)
        assert run_to_exit(r) == 4
        assert not r.spawned
        bail = json.loads((slice_dir / "bailout.json").read_text())
        assert bail["reason"] == "prerun_action" and bail["question"] is True
        assert f"- A2 — {PRERUN}" in bail["details"]
        assert "A1" not in bail["details"], "an after-run action never refuses"
        tool = Path(run_loop.__file__).resolve().parent / "close_out.py"
        assert (f"`python3 {tool} strike {slice_dir} <id> --reason "
                '"<what was done>" --by <who>`') in bail["details"]
        assert "relaunch with --resume" in bail["details"]
        state = load_state(slice_dir)
        assert state["run_phase"] == "phases"
        assert state["bailouts"][-1]["reason"] == "prerun_action"

        r = ScriptedLoop(slice_dir, [], resume=True, repo_root=repo)
        assert run_to_exit(r) == 4
        assert not r.spawned
        assert json.loads((slice_dir / "bailout.json").read_text())[
            "reason"] == "prerun_action"

        sys.modules["close_out"].strike_entry(
            slice_dir, "A2", "pushed and restarted", by="operator")
        r = ScriptedLoop(slice_dir, [V["exec_done"], V["review_signoff"],
                                     *TAIL], resume=True, repo_root=repo)
        assert run_to_exit(r) == 0
        assert r.spawned


def test_an_after_run_action_alone_never_refuses_the_run():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        report_with_actions(slice_dir, AFTER_RUN,
                            "Settle V3 after the operator's DNS cutover")
        r = ScriptedLoop(slice_dir, [V["exec_done"], V["review_signoff"],
                                     *TAIL], repo_root=repo)
        assert run_to_exit(r) == 0


def test_the_pre_run_match_takes_backticks_and_any_case():
    for headline in ("Before `/dev:run-slice`: publish the image",
                     "before /DEV:RUN-SLICE — publish the image"):
        with tempfile.TemporaryDirectory() as tmp:
            slice_dir, repo = make_slice(tmp)
            report_with_actions(slice_dir, headline)
            r = ScriptedLoop(slice_dir, [], repo_root=repo)
            assert run_to_exit(r) == 4, headline
            assert f"- A1 — {headline}" in json.loads(
                (slice_dir / "bailout.json").read_text())["details"]
    assert run_loop.open_prerun_actions(Path("/nonexistent")) == []
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, _ = make_slice(tmp, repo=False)
        close_out.init_report(slice_dir)
        assert run_loop.open_prerun_actions(slice_dir) == []


def test_a_dry_run_lists_open_pre_run_actions_without_failing():
    with tempfile.TemporaryDirectory() as tmp:
        root = dry_run_repo(tmp)
        slice_dir, _ = make_slice(tmp, repo=False)
        report_with_actions(slice_dir, AFTER_RUN, PRERUN)
        loop = RunLoop(slice_dir, resume=False)
        loop.repo_root = root
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            try:
                run_loop.cmd_dry_run(loop)
            except SystemExit as e:
                raise AssertionError(
                    f"dry run must pass, exited {e.code}") from None
        text = out.getvalue()
        assert ("  pre-run  A2  open — a real run stops on it until struck: "
                + PRERUN) in text
        assert "A1" not in text


# -- the installed-plugin and verification-key guards -----------------------

OURS = run_loop.plugin_version()


def write_installed(tmp, version, key="dev@aiworkflow", entries=None):
    """An installed_plugins.json in `tmp` naming `version` (None: no entry
    for this plugin) under `key`, beside another plugin's entry; returns
    (file, the entry's installPath)."""
    install = Path(tmp) / "cache" / "aiworkflow" / "dev" / str(version)
    plugins = {"kubecoder@kubecoder-config": [
        {"scope": "user", "installPath": "/elsewhere", "version": "0.8.4"}]}
    if entries is not None:
        plugins[key] = entries
    elif version is not None:
        plugins[key] = [{"scope": "user", "installPath": str(install),
                         "version": version}]
    path = Path(tmp) / "installed_plugins.json"
    path.write_text(json.dumps({"version": 2, "plugins": plugins}))
    return path, install


def installs(path, version):
    """A script step's effect: the marketplace updated the plugin mid-run."""
    def effect(loop):
        write_installed(path.parent, version)
    return effect


def test_installed_plugin_picks_the_entry_by_cache_layout_or_sole_key():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "installed_plugins.json"
        cached = Path("/h/.claude/plugins/cache/aiworkflow/dev/0.9.1/tools")
        repo = Path("/work/AIWorkflow/plugins/dev/tools")

        def with_keys(**keys):
            path.write_text(json.dumps({"plugins": {
                k.replace("_", "@"): [{"scope": "user", "version": v,
                                       "installPath": f"/i/{v}"}]
                for k, v in keys.items()}}))

        with patched(run_loop, INSTALLED_PLUGINS=path):
            with_keys(dev_aiworkflow="1.0", dev_fork="2.0")
            assert run_loop.installed_plugin(cached) == ("1.0", "/i/1.0"), \
                "the cache layout names the marketplace"
            assert run_loop.installed_plugin(repo) is None, \
                "two dev@ keys and no layout to choose by"
            with_keys(dev_aiworkflow="1.0", kubecoder_cfg="0.8")
            assert run_loop.installed_plugin(repo) == ("1.0", "/i/1.0"), \
                "outside the cache the sole dev@ key is taken"
            with_keys(dev_fork="2.0")
            assert run_loop.installed_plugin(cached) is None, \
                "the layout's key is absent"
            with_keys(kubecoder_cfg="0.8")
            assert run_loop.installed_plugin(repo) is None


def test_installed_plugin_prefers_the_user_install_and_reads_no_junk():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path("/work/AIWorkflow/plugins/dev/tools")
        project = {"scope": "project", "version": "3.0", "installPath": "/p"}
        user = {"scope": "user", "version": "1.0", "installPath": "/u"}
        cases = [
            ([project, user], ("1.0", "/u")),
            ([project], ("3.0", "/p")),
            ([project, dict(project, installPath="/q")], None),
            ([{"scope": "user", "installPath": "/u"}], None),
            ([{"scope": "user", "version": "1.0"}], ("1.0", "")),
            ({"scope": "user", "version": "1.0"}, None),
        ]
        for entries, want in cases:
            path, _ = write_installed(tmp, None, entries=entries)
            with patched(run_loop, INSTALLED_PLUGINS=path):
                assert run_loop.installed_plugin(repo) == want, entries
        path = Path(tmp) / "installed_plugins.json"
        for junk in ("{not json", "[]", '{"plugins": []}'):
            path.write_text(junk)
            with patched(run_loop, INSTALLED_PLUGINS=path):
                assert run_loop.installed_plugin(repo) is None, junk
        with patched(run_loop, INSTALLED_PLUGINS=Path(tmp) / "absent.json"):
            assert run_loop.installed_plugin(repo) is None


def test_a_plugin_version_mismatch_bails_at_startup_and_resumes_on_relaunch():
    """The loop runs the plugin it was launched from; its agents load the
    installed one. A difference is an error before anything is dispatched,
    naming the installed loop to relaunch — which resumes as usual."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        path, install = write_installed(tmp, "0.0.1")
        r = ScriptedLoop(slice_dir, [], repo_root=repo)
        with patched(run_loop, INSTALLED_PLUGINS=path):
            assert run_to_exit(r) == 3
        assert not r.spawned
        bail = json.loads((slice_dir / "bailout.json").read_text())
        assert bail["reason"] == "plugin_version"
        assert not bail["question"]
        assert f"runs plugin {OURS}" in bail["details"]
        assert "installed plugin is 0.0.1" in bail["details"]
        assert str(install / "tools" / "run_loop.py") in bail["details"]
        assert "--resume" in bail["details"]
        assert load_state(slice_dir)["bailouts"][0]["reason"] == \
            "plugin_version"

        write_installed(tmp, OURS)
        r = ScriptedLoop(slice_dir, [V["exec_done"], V["review_signoff"],
                                     *TAIL], resume=True, repo_root=repo)
        with patched(run_loop, INSTALLED_PLUGINS=path):
            assert run_to_exit(r) == 0
        assert not r.script


def test_a_matching_or_unknown_installed_plugin_proceeds():
    """Fail open: a missing file or a file without this plugin's entry is no
    evidence of a mismatch."""
    for version in (OURS, None, "absent"):
        with tempfile.TemporaryDirectory() as tmp:
            slice_dir, repo = make_slice(tmp)
            path, _ = write_installed(tmp, version)
            if version == "absent":
                path.unlink()
            r = ScriptedLoop(slice_dir, [V["exec_done"], V["review_signoff"],
                                         *TAIL], repo_root=repo)
            with patched(run_loop, INSTALLED_PLUGINS=path):
                assert run_to_exit(r) == 0, version
            assert not r.script


def test_an_install_mid_run_bails_before_the_next_dispatch():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        path, _ = write_installed(tmp, OURS)
        script = [(*V["exec_done"], installs(path, "9.9.9")),
                  V["review_signoff"], *TAIL]
        r = SpawningLoop(slice_dir, script, repo_root=repo)
        with patched(run_loop, run_kc_session=r.run_kc_session,
                     INSTALLED_PLUGINS=path):
            assert run_to_exit(r) == 3
        assert [s[0] for s in r.sessions] == ["code-writer"], \
            "the reviewer is never dispatched"
        bail = json.loads((slice_dir / "bailout.json").read_text())
        assert bail["reason"] == "plugin_version"
        assert "installed plugin is 9.9.9" in bail["details"]


def test_an_install_mid_run_bails_before_a_nudge():
    """A nudge resumes a session under the installed plugin just the same."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        path, _ = write_installed(tmp, OURS)
        script = [("code-writer", "forgot the verdict",
                   installs(path, "9.9.9"))]
        r = SpawningLoop(slice_dir, script, repo_root=repo)
        with patched(run_loop, run_kc_session=r.run_kc_session,
                     INSTALLED_PLUGINS=path):
            assert run_to_exit(r) == 3
        assert len(r.sessions) == 1, "the verdict nudge is never sent"
        bail = json.loads((slice_dir / "bailout.json").read_text())
        assert bail["reason"] == "plugin_version"


# -- the skills a plan names (AIWF-56) ----------------------------------------
#
# Every role is spawned without the Skill tool, and the plans of Ansible 046
# and 056 and DHCPApp 001 named `kubecoder:jenkins-pipelines` for the work:
# their writers spent turns finding it on disk, among seven cached versions.

def skills_installed(tmp, *skills):
    """installed_plugins.json in `tmp`: kubecoder's install holding `skills`,
    and this plugin's at this tree's version (the guard passes) holding one
    of its own; returns (file, kubecoder's install)."""
    kc = Path(tmp) / "cache" / "kubecoder-config" / "kubecoder" / "0.10.12"
    ours = Path(tmp) / "cache" / "aiworkflow" / "dev" / str(OURS)
    for root, names in ((kc, skills), (ours, ("run-slice",))):
        for name in names:
            (root / "skills" / name).mkdir(parents=True)
            (root / "skills" / name / "SKILL.md").write_text(f"# {name}\n")
    path = Path(tmp) / "installed_plugins.json"
    path.write_text(json.dumps({"version": 2, "plugins": {
        "kubecoder@kubecoder-config": [
            {"scope": "user", "installPath": str(kc), "version": "0.10.12"}],
        "dev@aiworkflow": [
            {"scope": "user", "installPath": str(ours), "version": OURS}]}}))
    return path, kc


def skill_md(install, name):
    return install / "skills" / name / "SKILL.md"


SKILL_HEADER = ("\nSkills this phase names. This session has no Skill tool: "
                "each skill is the\nfile named here — read it before the work "
                "it governs.\n")


def by_phase(loop):
    """(role, phase id, prompt) per dispatch, in order."""
    return [(s[0], s[1], p) for s, (_, p) in zip(loop.spawned, loop.prompts,
                                                  strict=True)]


def test_resolve_skills_takes_the_backticked_names_of_installed_plugins():
    with tempfile.TemporaryDirectory() as tmp:
        path, kc = skills_installed(tmp, "jenkins-pipelines")
        text = ("Load the `kubecoder:jenkins-pipelines` skill before the "
                "file, and `kubecoder:no-such`. `origin:main` is a ref, "
                "`dev:run-slice` this plugin's own skill, and "
                "`kubecoder:jenkins-pipelines` is named once.")
        with patched(run_loop, INSTALLED_PLUGINS=path):
            assert run_loop.resolve_skills(text) == [
                ("kubecoder:jenkins-pipelines",
                 skill_md(kc, "jenkins-pipelines")),
                ("kubecoder:no-such", None)]
            for bare in ("Load kubecoder:jenkins-pipelines first.",
                         "`kubecoder:jenkins-pipelines/SKILL.md`",
                         "`kubecoder:Jenkins`"):
                assert run_loop.resolve_skills(bare) == [], bare
        path.write_text("{not json")
        with patched(run_loop, INSTALLED_PLUGINS=path):
            assert run_loop.resolve_skills(text) == []
        with patched(run_loop, INSTALLED_PLUGINS=Path(tmp) / "absent.json"):
            assert run_loop.resolve_skills(text) == []


def test_resolve_skills_reads_the_install_an_interactive_session_loads():
    """The user-scope install of the plugin, whichever key holds it; with
    none of them the user's, the first key in file order with a lone one."""
    with tempfile.TemporaryDirectory() as tmp:
        roots = {}
        for version in ("old", "new", "proj"):
            roots[version] = Path(tmp) / version
            (roots[version] / "skills" / "s").mkdir(parents=True)
            (roots[version] / "skills" / "s" / "SKILL.md").write_text("s\n")

        def entry(scope, version):
            return {"scope": scope, "installPath": str(roots[version]),
                    "version": version}

        cases = [
            ({"kc@a": [entry("project", "proj")],
              "kc@b": [entry("user", "new")]}, "new"),
            ({"kc@a": [entry("project", "proj"), entry("user", "new")]},
             "new"),
            ({"kc@a": [entry("project", "old")],
              "kc@b": [entry("project", "new")]}, "old"),
            ({"kc@a": [entry("project", "old"), entry("project", "proj")],
              "kc@b": [entry("project", "new")]}, "new"),
        ]
        path = Path(tmp) / "installed_plugins.json"
        for plugins, want in cases:
            path.write_text(json.dumps({"plugins": plugins}))
            with patched(run_loop, INSTALLED_PLUGINS=path):
                assert run_loop.resolve_skills("`kc:s`") == [
                    ("kc:s", skill_md(roots[want], "s"))], plugins
        path.write_text(json.dumps({"plugins": {
            "kc@a": [entry("project", "old"), entry("project", "new")]}}))
        with patched(run_loop, INSTALLED_PLUGINS=path):
            assert run_loop.resolve_skills("`kc:s`") == [("kc:s", None)], \
                "installed, but no install to read it from"


def test_a_skill_the_phase_names_reaches_its_writer_and_reviewer_rounds():
    """The executor, a gate-fix and a review-fix round, the full and the
    delta review of the phase whose section names the skill each carry its
    installed file; the next phase, which names none, and the slice's tail
    are dispatched as they always were."""
    with tempfile.TemporaryDirectory() as tmp:
        path, kc = skills_installed(tmp, "jenkins-pipelines")
        slice_dir, repo = make_slice(tmp, phases=[
            phase_section("1", "The Jenkinsfile",
                          body="Load the `kubecoder:jenkins-pipelines` skill "
                               "before writing the file.\n"),
            ("2", "The rest")])

        def fixes(loop):
            loop.fake_git.head = "fixhead"

        script = [V["exec_done"], V["exec_done"],         # executor, gate fix
                  V["review_issues"], (*V["exec_done"], fixes),
                  V["review_signoff"],                    # the delta round
                  V["exec_done"], V["review_signoff"], *TAIL]
        r = ScriptedLoop(slice_dir, script, gates=[False, True],
                         repo_root=repo)
        with patched(run_loop, INSTALLED_PLUGINS=path):
            assert run_to_exit(r) == 0 and not r.script
        line = (SKILL_HEADER + "- `kubecoder:jenkins-pipelines`: "
                f"{skill_md(kc, 'jenkins-pipelines')}\n")
        named = [(role, p) for role, pid, p in by_phase(r) if pid == "1"]
        assert [role for role, _ in named] == ["code-writer"] * 2 + [
            "code-reviewer", "code-writer", "code-reviewer"]
        assert "Re-review phase P1" in named[-1][1]
        for role, prompt in named:
            assert prompt.count(line) == 1, role
        for role, pid, prompt in by_phase(r):
            if pid != "1":
                assert "Skills this phase names" not in prompt, (role, pid)
        log = (slice_dir / "log.txt").read_text()
        assert log.count("[P1] skills named — kubecoder:jenkins-pipelines\n") \
            == 5
        assert "[P2] skills named" not in log


def test_a_skill_the_plans_own_text_names_reaches_every_phase():
    """Text outside every phase section — the rulings above the phases, a
    not-in-scope below them — is every phase's; a phase's own section is its
    alone, and a skill its plugin lacks is said once, not searched for."""
    with tempfile.TemporaryDirectory() as tmp:
        path, kc = skills_installed(tmp, "jenkins-pipelines", "kubecoder-api")
        slice_dir, repo = make_slice(tmp, phases=[
            ("1", "First"),
            phase_section("2", "Second",
                          body="Mind `kubecoder:no-such` here.\n")])
        plan = slice_dir / "plan.md"
        plan.write_text(plan.read_text().replace(
            "## Phases\n",
            "## Requirements / rulings\n\n- R1. Every Jenkinsfile follows "
            "`kubecoder:jenkins-pipelines`.\n\n## Phases\n")
            + "\n## Not in scope\n\n- The `kubecoder:kubecoder-api` client.\n")
        r = ScriptedLoop(slice_dir, [V["exec_done"], V["review_signoff"],
                                     V["exec_done"], V["review_signoff"],
                                     *TAIL], repo_root=repo)
        with patched(run_loop, INSTALLED_PLUGINS=path):
            assert run_to_exit(r) == 0 and not r.script
        jenkins = ("- `kubecoder:jenkins-pipelines`: "
                   f"{skill_md(kc, 'jenkins-pipelines')}\n")
        api = f"- `kubecoder:kubecoder-api`: {skill_md(kc, 'kubecoder-api')}\n"
        missing = ("- `kubecoder:no-such`: the installed kubecoder plugin has "
                   "no such skill — work without it, and do not search for "
                   "it.\n")
        want = {"1": SKILL_HEADER + jenkins + api,
                "2": SKILL_HEADER + jenkins + missing + api}
        dispatched = [(role, pid, p) for role, pid, p in by_phase(r)
                      if role in ("code-writer", "code-reviewer")]
        assert len(dispatched) == 4
        for role, pid, prompt in dispatched:
            assert want[pid] in prompt, (role, pid)
        log = (slice_dir / "log.txt").read_text()
        assert ("[P2] skills named — kubecoder:jenkins-pipelines, "
                "kubecoder:no-such (not installed), kubecoder:kubecoder-api"
                in log)


def test_a_plan_naming_no_skill_dispatches_as_it_always_did():
    """A backticked ref, this plugin's own skill and a bare name are no
    skill to point at: no line, and nothing logged."""
    with tempfile.TemporaryDirectory() as tmp:
        path, _ = skills_installed(tmp, "jenkins-pipelines")
        slice_dir, repo = make_slice(tmp, phases=[phase_section(
            "1", "First",
            body="Rebase on `origin:main`, run `dev:run-slice`, and mind "
                 "kubecoder:jenkins-pipelines.\n")])
        script = [V["exec_done"], V["review_issues"], V["exec_done"],
                  V["review_signoff"], *TAIL]
        r = ScriptedLoop(slice_dir, script, repo_root=repo)
        with patched(run_loop, INSTALLED_PLUGINS=path):
            assert run_to_exit(r) == 0 and not r.script
        assert len(r.prompts) == len(script)
        for role, prompt in r.prompts:
            assert "Skills this phase names" not in prompt, role
        assert "skills named" not in (slice_dir / "log.txt").read_text()


def test_phase_scope_cuts_every_other_phase():
    plan = ("# Plan\n\n## Requirements / rulings\n\nR.\n\n## Phases\n\n"
            "### P1 — One\n\nTarget: app\n\none\n\n#### Its own part\n\n"
            "still one\n\n"
            "### P2 — Two\n\nTarget: app\n\ntwo\n\n"
            "## Not in scope\n\nnot this\n")
    one = run_loop.phase_scope(plan, "1")
    assert "R." in one and "still one" in one and "not this" in one
    assert "### P2" not in one and "two" not in one
    two = run_loop.phase_scope(plan, "2")
    assert "two" in two and "not this" in two and "one" not in two


FULL_ITEM = {"id": "V01", "area": "a", "description": "it works",
             "owed_after": "../HelmCharts", "verdict": None, "rationale": "",
             "evidence": []}


def test_an_unknown_verification_key_bails():
    """A key this driver does not know is one it would silently ignore —
    at startup and when an agent writes one mid-run."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        (slice_dir / "verification.json").write_text(json.dumps({"items": [
            FULL_ITEM, dict(FULL_ITEM, id="V02", surprise=1, also=2)]}))
        r = ScriptedLoop(slice_dir, [], repo_root=repo)
        assert run_to_exit(r) == 3
        assert not r.spawned
        bail = json.loads((slice_dir / "bailout.json").read_text())
        assert bail["reason"] == "protocol_failure"
        assert "V02 `also`, V02 `surprise`" in bail["details"]
        assert "V01" not in bail["details"]
        assert f"plugin {OURS}" in bail["details"]

    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)

        def writes_unknown(loop):
            (slice_dir / "verification.json").write_text(json.dumps(
                {"items": [dict(FULL_ITEM, newer=True)]}))

        r = ScriptedLoop(slice_dir, [(*V["exec_done"], writes_unknown),
                                     V["review_signoff"]], repo_root=repo)
        assert run_to_exit(r) == 3
        assert [s[0] for s in r.spawned] == ["code-writer"]
        bail = json.loads((slice_dir / "bailout.json").read_text())
        assert bail["reason"] == "protocol_failure"
        assert "V01 `newer`" in bail["details"]


def test_the_full_verification_schema_proceeds():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        assert set(FULL_ITEM) == run_loop.VERIFICATION_ITEM_KEYS
        (slice_dir / "verification.json").write_text(
            json.dumps({"items": [FULL_ITEM]}))
        r = ScriptedLoop(slice_dir, [V["exec_done"], V["review_signoff"],
                                     *TAIL], repo_root=repo)
        assert run_to_exit(r) == 0
        assert not r.script


# -- driver rulings -------------------------------------------------------------
#
# `## Driver rulings` is the operator overriding a fixed rule of the loop for
# one target: a gate the environment cannot run (waived, with the substitute
# that proves it instead), a red that predates the slice (accepted), prd for
# a repo the slice must roll. Before it, an unrunnable suite spent the fix
# cap and bailed `gate_red` at every phase, and the operator's only lever was
# hand-editing state.json.

parse_rulings = run_loop.parse_rulings

GATE_RULING = "gate app — Jenkins validation build — suites need Postgres"


def ruled_plan(slice_dir, *rulings, body=None):
    """plan.md with a `## Driver rulings` section holding `rulings` — the
    one-phase plan make_slice writes, unless `body` says otherwise."""
    (slice_dir / "plan.md").write_text(
        "# plan\n\n## Driver rulings\n\n"
        + "".join(f"- {r}\n" for r in rulings) + "\n"
        + (body if body is not None else phase_section("1", "First phase")))


def test_parse_rulings_reads_each_kind_and_the_section_only():
    text = (
        "# Plan\n\n## Requirements / rulings\n\n- gate app — not — here\n\n"
        "## Driver rulings\n\n"
        "<!-- Optional. `- gate <target> — <substitute> — <why>` -->\n\n"
        "prose about the rulings is fine\n\n"
        "- gate ../ElectronicsInventory — Jenkins validation build — "
        "suites need Postgres + MinIO — not declared here\n"
        "- gate `web` — none — no environment runs it\n"
        "- accept ../Ansible lint — red before this slice, ANS-99\n"
        "- accept **`backend`** `test` — flaky upstream fixture, ANS-101\n"
        "- prd ../Ansible — roll prd once dev verifies (operator, "
        "2026-09-26)\n\n"
        "## Push holds\n\n- gate app — not — a ruling\n"
        "\n### P1 — First\n\nTarget: app\n")
    rulings, errors = parse_rulings(text)
    assert errors == []
    got = [(r.kind, r.target, r.verb, r.substitute, r.why) for r in rulings]
    assert got == [
        ("gate", "../ElectronicsInventory", "test",
         "Jenkins validation build",
         "suites need Postgres + MinIO — not declared here"),
        ("gate", "web", "test", None, "no environment runs it"),
        ("accept", "../Ansible", "lint", None, "red before this slice, ANS-99"),
        ("accept", "backend", "test", None, "flaky upstream fixture, ANS-101"),
        ("prd", "../Ansible", None, None,
         "roll prd once dev verifies (operator, 2026-09-26)"),
    ]
    assert rulings[1].substitute_text == "no substitute"
    assert [r.key for r in rulings][2:] == [
        "accept ../Ansible lint", "accept backend test", "prd ../Ansible"]


def test_parse_rulings_errors():
    """A bullet the parser cannot read is an error, never a skip: a ruling
    it misses silently is a gate the driver runs anyway."""
    text = ("## Driver rulings\n\n"
            "- waive app — Jenkins — why\n"
            "- gate app — Jenkins\n"
            "- accept app deploy — not a sweep verb\n"
            "- accept app — no verb\n"
            "- prd app\n"
            "- prd ../A — first\n"
            "- prd ../A — again\n"
            "- accept app lint — one\n"
            "- accept app build — another verb is another ruling\n")
    rulings, errors = parse_rulings(text)
    assert [r.key for r in rulings] == [
        "prd ../A", "accept app lint", "accept app build"]
    joined = "\n".join(errors)
    for bad in ("waive app — Jenkins — why", "gate app — Jenkins",
                "accept app deploy", "accept app — no verb", "- prd app`"):
        assert bad in joined, bad
    assert joined.count("is not a driver ruling") == 5
    assert "`prd ../A` is ruled twice" in joined


def test_parse_rulings_absent_section():
    assert parse_rulings("# Plan\n\n### P1 — X\n\nTarget: app\n") == ([], [])


def test_an_unresolvable_ruling_is_a_plan_structure_error():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        ruled_plan(slice_dir, "gate ../Nope — Jenkins — no suite here")
        r = ScriptedLoop(slice_dir, [], repo_root=repo)
        assert run_to_exit(r) == 4
        bail = json.loads((slice_dir / "bailout.json").read_text())
        assert bail["reason"] == "plan_doc" and bail["question"] is True
        assert "driver ruling `gate ../Nope`" in bail["details"]


def test_a_ruling_covers_its_component_its_repo_or_a_whole_repo_target():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        sib = make_sibling(tmp)
        r = ScriptedLoop(slice_dir, [], repo_root=repo)

        def ruling(target, kind="project", root=repo):
            return (run_loop.Ruling("gate", target, "why"),
                    run_loop.ResolvedTarget(target, kind, root, None, root))

        app, web = ruling("app"), ruling("web")
        whole = ruling("../Sibling", "sibling", sib)
        # a component ruling covers that component alone
        assert r._covering([app], repo, "app") is app[0]
        assert r._covering([app], repo, "web") is None
        assert r._covering([app], sib, "app") is None
        # a repo-level ruling covers every component of its repo
        assert r._covering([whole], sib, "anything") is whole[0]
        # a whole-repo target is covered by any ruling in that repo
        assert r._covering([web], repo, None) is web[0]
        # the component's own ruling wins over a repo-level one
        repo_wide = ruling("../repo", "sibling", repo)
        assert r._covering([repo_wide, app], repo, "app") is app[0]


def test_a_waived_phase_gate_runs_nothing_and_says_why():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        ruled_plan(slice_dir, GATE_RULING)
        # a red gate would spend a fix round: waived, it is never consulted
        r = ScriptedLoop(slice_dir, [V["exec_done"], V["review_signoff"],
                                     *TAIL],
                         repo_root=repo, gates=[False] * 4)
        assert run_to_exit(r) == 0
        assert not r.script, "no fix round was spawned"
        assert r.gate_calls == []
        ps = load_state(slice_dir)["phases"]["1"]
        assert ps["status"] == "merged" and ps["gate_fix_rounds"] == 0
        assert not ps.get("gate_green_commit")
        writer = next(p for role, p in r.prompts
                      if role == "code-writer").replace("\n", " ")
        assert ("The driver's test gate for app is waived by the operator's "
                "ruling in plan.md's `## Driver rulings` (substitute: Jenkins "
                "validation build — suites need Postgres)") in writer
        assert "is not this phase's to fix" in writer
        reviewer = next(p for role, p in r.prompts
                        if role == "code-reviewer").replace("\n", " ")
        assert ("The driver did not run the test gate on this commit: "
                "plan.md's `## Driver rulings` waives it for app, naming "
                "`Jenkins validation build` as the gate") in reviewer
        assert "ran GREEN" not in reviewer
        assert "waived by plan.md's `## Driver rulings`" \
            in (slice_dir / "log.txt").read_text()
        events = entries_in_full(slice_dir)
        assert events.count("Gate waived by ruling") == 1
        assert "Gate waived by ruling: app — Jenkins validation build" \
            in events
        assert "the driver's phase gate, against `plan.md`'s `## Driver " \
            "rulings`" in events.replace("\n", " ")
        assert load_state(slice_dir)["rulings_reported"] == ["gate app"]


def test_the_merge_re_gate_is_waived_too():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        ruled_plan(slice_dir, GATE_RULING)
        r = KcExitLoop(slice_dir, [V["exec_done"], V["review_signoff"],
                                   *TAIL],
                       repo_root=repo, gate_rcs=[1] * 4)
        assert run_to_exit(r) == 0
        # the sweep's lint and build ran; no `test` ran anywhere
        assert [argv[2] for argv, _, _ in r.kc_runs] == ["lint", "build"]
        assert not [h for h in load_state(slice_dir)["history"]
                    if h["role"] == "gate"]


def test_a_waived_sweep_test_row_is_not_run_and_lint_build_still_are():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        ruled_plan(slice_dir, GATE_RULING)
        r = ScriptedLoop(slice_dir, [V["exec_done"], V["review_signoff"],
                                     *TAIL], repo_root=repo)
        assert run_to_exit(r) == 0
        assert r.sweep_calls == [(str(repo), PROJECT, "lint"),
                                 (str(repo), PROJECT, "build")]
        state = load_state(slice_dir)
        sweep = state["gate_sweep"]
        test_row = next(row for row in sweep["results"]
                        if row["verb"] == "test")
        assert test_row["outcome"] == "waived" and test_row["green"] is False
        assert test_row["substitute"] == "Jenkins validation build"
        assert sweep["outcome"] == "green"
        row = next(h for h in state["history"] if h["role"] == "sweep")
        assert row["summary"] == "3 command(s) (1 waived by ruling)"
        for role in ("consult", "test-agent"):
            prompt = next(p for rl, p in r.prompts if rl == role)
            flat = prompt.replace("\n", " ")
            assert (f"{PROJECT} test → WAIVED by ruling — substitute: "
                    "Jenkins validation build (suites need Postgres)\n"
                    in prompt)
            assert "Every row that ran and no ruling covers is GREEN" in flat
            assert "Every row that ran is GREEN" not in flat
            assert "it does not block the push" in flat
        test_prompt = next(p for rl, p in r.prompts if rl == "test-agent")
        assert "waive the driver's test gate for these" in test_prompt
        assert ("  - app — substitute: Jenkins validation build — suites "
                "need Postgres") in test_prompt
        # the phase gate reported it first; the sweep adds no second entry
        assert entries_in_full(slice_dir).count("Gate waived by ruling") == 1


def test_an_accepted_red_row_does_not_block():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        ruled_plan(slice_dir, "accept app lint — red before this slice, "
                              "ANS-99")
        r = ScriptedLoop(slice_dir, [V["exec_done"], V["review_signoff"],
                                     *TAIL], repo_root=repo,
                         sweep_reds={(PROJECT, "lint"), (PROJECT, "build")})
        # build is red too, and no ruling covers it: still a red sweep
        assert run_to_exit(r) == 0
        consult = next(p for rl, p in r.prompts if rl == "consult")
        assert (f"{PROJECT} lint → RED, accepted by ruling (red before this "
                "slice, ANS-99) — ") in consult
        assert f"{PROJECT} build → RED — " in consult
        assert "append a phase that fixes it" in consult.replace("\n", " ")
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        ruled_plan(slice_dir, "accept app lint — red before this slice, "
                              "ANS-99")
        r = ScriptedLoop(slice_dir, [V["exec_done"], V["review_signoff"],
                                     *TAIL], repo_root=repo,
                         sweep_reds={(PROJECT, "lint")})
        assert run_to_exit(r) == 0
        # the record keeps what ran; the rulings are applied as it renders
        assert load_state(slice_dir)["gate_sweep"]["outcome"] == "red"
        for role in ("consult", "test-agent"):
            flat = next(p for rl, p in r.prompts
                        if rl == role).replace("\n", " ")
            assert "Every row that ran and no ruling covers is GREEN" in flat
            assert "A WAIVED or accepted row is the operator's ruling" in flat
            assert "append a phase that fixes it" not in flat
            assert "does not leave the machine" not in flat
        events = entries_in_full(slice_dir)
        assert events.count("Red row accepted by ruling: app lint") == 1
        assert "the driver's sweep" in events


def test_a_ruling_added_after_the_sweep_is_honoured_when_it_renders():
    """The sweep record is reused while no head moves — across a resume
    too — so the rulings are applied when it renders, not when it ran."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        script = [V["exec_done"], V["review_signoff"], V["consult_complete"],
                  ("test-agent", {"outcome": "blocked", "summary": "red"})]
        r1 = ScriptedLoop(slice_dir, script, repo_root=repo,
                          sweep_reds={(PROJECT, "test")})
        assert run_to_exit(r1) == 3
        first = next(p for rl, p in r1.prompts if rl == "test-agent")
        assert "does not leave the machine" in first.replace("\n", " ")
        # the operator rules while the run sits at the bail — on a state
        # an older plugin wrote, without the reported-rulings record
        ruled_plan(slice_dir, GATE_RULING,
                   body=phase_section("1", "First phase", done=True))
        state = load_state(slice_dir)
        del state["rulings_reported"]
        (slice_dir / "state.json").write_text(json.dumps(state))
        r2 = ScriptedLoop(slice_dir, [V["test_clean"], V["doc_done"]],
                          resume=True, repo_root=repo,
                          sweep_reds={(PROJECT, "test")})
        assert run_to_exit(r2) == 0
        assert r2.sweep_calls == [], "same heads: the record is reused"
        prompt = next(p for rl, p in r2.prompts if rl == "test-agent")
        assert (f"{PROJECT} test → WAIVED by ruling (ran RED) — substitute: "
                "Jenkins validation build") in prompt
        assert "does not leave the machine" not in prompt.replace("\n", " ")
        events = entries_in_full(slice_dir)
        assert events.count("Gate waived by ruling: app") == 1
        assert "the driver's sweep" in events


def test_a_withdrawn_gate_ruling_re_runs_the_waived_row():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        ruled_plan(slice_dir, GATE_RULING)
        script = [V["exec_done"], V["review_signoff"], V["consult_complete"],
                  ("test-agent", {"outcome": "blocked", "summary": "stuck"})]
        r1 = ScriptedLoop(slice_dir, script, repo_root=repo)
        assert run_to_exit(r1) == 3
        assert (str(repo), PROJECT, "test") not in r1.sweep_calls
        (slice_dir / "plan.md").write_text(
            "# plan\n\n" + phase_section("1", "First phase", done=True))
        r2 = ScriptedLoop(slice_dir, [V["test_clean"], V["doc_done"]],
                          resume=True, repo_root=repo)
        assert run_to_exit(r2) == 0
        assert (str(repo), PROJECT, "test") in r2.sweep_calls


def test_doc_gate_runs_ruled_verbs_per_component():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        ruled_plan(slice_dir, GATE_RULING,
                   "accept web lint — red before this slice, ANS-99")
        loop = RunLoop(slice_dir, resume=False)
        loop.repo_root = repo
        loop.project_dirs = {"app": repo, "web": repo}
        loop.state = {"history": []}
        calls = []
        reds = {("lint", "web")}

        def fake_exec(argv, log_file):
            calls.append(" ".join(argv[2:]))
            return 1 if (argv[2], argv[-1]) in reds else 0

        loop._doc_gate_exec = fake_exec
        ds = {"gate_runs": 0}
        with patched(run_loop, load_project_dirs=lambda cwd: {
                "app": Path(cwd), "web": Path(cwd)}):
            green, log_path = loop._run_doc_gate(ds)
            assert green
            # lint and test are ruled on here, so they run per component;
            # build is not, so it runs whole-repo as before
            assert calls == ["lint --project app", "lint --project web",
                             "build", "test --project web"]
            text = log_path.read_text()
            assert ("$ kc project test --project app → waived by plan.md's "
                    "`## Driver rulings`") in text
            assert "→ RED, accepted by plan.md's `## Driver rulings`" in text
            assert loop.state["rulings_reported"] == ["accept web lint",
                                                      "gate app"]
            # a red no ruling covers is still red, and still fail-fast
            calls.clear()
            reds.add(("lint", "app"))
            green, _ = loop._run_doc_gate(ds)
            assert not green and calls == ["lint --project app"]


def test_doc_gate_ignores_rulings_on_another_repo():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        make_sibling(tmp)
        ruled_plan(slice_dir, "gate ../Sibling — Jenkins — no Postgres here")
        loop = RunLoop(slice_dir, resume=False)
        loop.repo_root = repo
        loop.project_dirs = {PROJECT: repo}
        loop.state = {"history": []}
        calls = []
        loop._doc_gate_exec = lambda argv, log_file: calls.append(
            " ".join(argv[2:])) or 0
        green, _ = loop._run_doc_gate({"gate_runs": 0})
        assert green and calls == ["lint", "build", "test"]


def test_prd_is_authorized_only_by_a_prd_ruling():
    unchanged = ("pre-authorized — do not ask for permission.\n"
                 "  Pushing is this phase's, production included, wherever the project's\n"
                 "  deploy path is a push. Running a promotion pipeline is operator-gated —\n"
                 "  assume one wherever the project has more than one stage, unless its\n"
                 "  deploy-operations doc says the stages are separate environments with\n"
                 "  nothing promoted between them; nothing here runs it.\n"
                 "- The slice folder")
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        ruled_plan(slice_dir, GATE_RULING)
        r = ScriptedLoop(slice_dir, [V["exec_done"], V["review_signoff"],
                                     *TAIL], repo_root=repo)
        assert run_to_exit(r) == 0
        prompt = next(p for rl, p in r.prompts if rl == "test-agent")
        assert unchanged in prompt
        assert "prd authorized" not in load_report(slice_dir)
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        ruled_plan(slice_dir, "prd app — roll prd once dev verifies")
        script = [V["exec_done"], V["review_signoff"], V["consult_complete"],
                  ("test-agent", {"outcome": "blocked", "summary": "stuck"})]
        r1 = ScriptedLoop(slice_dir, script, repo_root=repo)
        assert run_to_exit(r1) == 3
        prompt = next(p for rl, p in r1.prompts if rl == "test-agent")
        assert "nothing here runs it" not in prompt
        flat = " ".join(prompt.split())
        assert ("nothing promoted between them — except for these targets, which "
                "plan.md's `## Driver rulings` authorize: running their promotion "
                "pipeline is part of this test phase:") in flat
        assert "  - app — roll prd once dev verifies\n- The slice" in prompt
        # the resume dispatches the test phase again; the entry stays one
        r2 = ScriptedLoop(slice_dir, [V["test_clean"], V["doc_done"]],
                          resume=True, repo_root=repo)
        assert run_to_exit(r2) == 0
        events = entries_in_full(slice_dir)
        assert events.count("prd authorized by ruling: app") == 1
        assert "the driver's test-phase dispatch" in events


def test_dry_run_prints_the_rulings():
    with tempfile.TemporaryDirectory() as tmp:
        root = dry_run_repo(tmp)
        slice_dir, _ = make_slice(tmp, repo=False)
        ruled_plan(slice_dir, GATE_RULING, "accept app lint — ANS-99",
                   "prd ../Nope — nowhere")
        loop = RunLoop(slice_dir, resume=False)
        loop.repo_root = root
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                run_loop.cmd_dry_run(loop)
            except SystemExit as e:
                assert e.code == 2
            else:
                raise AssertionError("an unresolvable ruling must exit 2")
        text = out.getvalue()
        assert (f"  ruling  gate app  root={root}  gate waived, substitute: "
                "Jenkins validation build: suites need Postgres") in text
        assert f"  ruling  accept app lint  root={root}  red lint accepted" \
            in text
        assert "  ruling  prd ../Nope  INVALID" in text
        assert "driver ruling `prd ../Nope`" in err.getvalue()


# -- GitHub repo targets (AIWF-22) ---------------------------------------------
#
# `Target: github:<owner>/<repo>` is cloned into the scratch root and is a
# sibling repo path from then on. The clone itself is github_target's (its own
# suite runs real git); here `ensure_clone` is faked onto a sibling-shaped dir.

GITHUB = "github:acme/Widget"


def fake_clone(tmp, manifest=True):
    """(the clone, the `ensure_clone` calls as (target, owned), the patch)
    — a GitHub Target resolving to a checkout under a tmp scratch root."""
    scratch = Path(tmp) / "scratch"
    clone = scratch / "Widget"
    (clone / ".git").mkdir(parents=True)
    if manifest:
        (clone / ".kubecoder").mkdir()
        (clone / ".kubecoder" / "project.yaml").write_text("projects: []\n")
    calls = []

    def ensure(target, *, owned=False):
        calls.append((target, owned))
        return clone

    return clone, calls, patched(run_loop.github_target, SCRATCH_ROOT=scratch,
                                 ensure_clone=ensure)


def clone_headline(clone):
    return (f"The driver left a scratch clone at {clone.resolve()} "
            f"(`Target: {GITHUB}`)")


def test_a_github_target_resolves_as_a_sibling_at_its_clone():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        clone, calls, patch = fake_clone(tmp)
        bare, _, bare_patch = fake_clone(Path(tmp) / "bare", manifest=False)
        r = ScriptedLoop(slice_dir, [], repo_root=repo)
        with patch:
            target = r._resolve_target(GITHUB)
        assert (target.name, target.kind) == (GITHUB, "sibling")
        assert target.git_root == target.gate_cwd == clone.resolve()
        assert target.gate_argv == ["kc", "project", "test"]
        assert calls == [(GITHUB, False)]
        with bare_patch:
            assert r._resolve_target(GITHUB).gate_argv is None
            assert r._resolve_target(GITHUB).git_root == bare.resolve()


def test_a_github_target_is_never_a_component_name():
    """`Creates:` names a component; a GitHub target is a repo."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        _, _, patch = fake_clone(tmp)
        r = ScriptedLoop(slice_dir, [], repo_root=repo)
        with patch:
            target = r._resolve_target(GITHUB, creates=GITHUB)
        assert target.kind == "sibling"
        phases, _ = parse_plan("# p\n\n" + phase_section("1", "X", GITHUB)
                               + "\nCreates: " + GITHUB + "\n")
        assert run_loop.creation_claim(phases, 0) == (None, None)


def test_the_runs_own_clone_is_resolved_owned_and_a_dry_run_reads_it():
    """A resume over the run's own clone must not sync it (its base holds
    the merged, unpushed phases) — and neither may a dry run started while
    that run is live, which holds no state of its own."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        clone, calls, patch = fake_clone(tmp)
        r = ScriptedLoop(slice_dir, [], repo_root=repo)
        with patch:
            r.state = {"bases": {str(clone.resolve()): "main"}}
            r._resolve_target(GITHUB)
            r.state = {}
            r._resolve_target(GITHUB)
            (slice_dir / "state.json").write_text(json.dumps(
                {"bases": {str(clone.resolve()): "main"}}))
            r._resolve_target(GITHUB)
        assert calls == [(GITHUB, True), (GITHUB, False), (GITHUB, True)]


# AIWF-48: a ledger phase commits to /work/scratch clones no phase targets, so
# none of them is in `bases`. A `github:` hold on one was synced, refused for
# the commits origin lacks, and bailed the run as a plan structure error.

HELD_GITHUB_PLAN = (f"# plan\n\n## Push holds\n\n- {GITHUB} — the ledger's\n\n"
                    + phase_section("1", "Ledger work", "../Sibling"))


def test_an_existing_held_github_clone_resolves_owned_with_no_bases():
    with tempfile.TemporaryDirectory() as tmp:
        make_sibling(tmp)
        root = dry_run_repo(tmp)
        slice_dir, _ = make_slice(tmp, repo=False)
        (slice_dir / "plan.md").write_text(HELD_GITHUB_PLAN)
        clone, calls, patch = fake_clone(tmp)
        loop = RunLoop(slice_dir, resume=False)
        loop.repo_root = root
        out = io.StringIO()
        with patch:
            assert loop._push_holds(HELD_GITHUB_PLAN) == (
                {str(clone.resolve()): "the ledger's"}, [])
            with contextlib.redirect_stdout(out):
                try:
                    run_loop.cmd_dry_run(loop)
                except SystemExit as e:
                    raise AssertionError(
                        f"dry run must pass, exited {e.code}") from None
        assert calls == [(GITHUB, True), (GITHUB, True)]
        assert (f"  hold  {GITHUB}  root={clone.resolve()}  not pushed: "
                "the ledger's") in out.getvalue()


def test_a_held_github_clone_not_there_yet_is_cloned():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        clone, _, patch = fake_clone(tmp)
        shutil.rmtree(clone)
        calls = []

        def ensure(target, *, owned=False):
            calls.append((target, owned))
            (clone / ".git").mkdir(parents=True)
            return clone

        r = ScriptedLoop(slice_dir, [], repo_root=repo)
        with patch, patched(run_loop.github_target, ensure_clone=ensure):
            assert r._push_holds(HELD_GITHUB_PLAN)[0] == {
                str(clone.resolve()): "the ledger's"}
        assert calls == [(GITHUB, False)]


def test_a_github_target_the_plan_also_holds_still_resolves_as_a_target():
    """`held` is the hold's resolution only: a phase's Target outside
    `bases` is synced as before, held or not."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        (slice_dir / "plan.md").write_text(HELD_GITHUB_PLAN)
        _, calls, patch = fake_clone(tmp)
        r = ScriptedLoop(slice_dir, [], repo_root=repo)
        with patch:
            r.state = {}
            r._resolve_target(GITHUB)
        assert calls == [(GITHUB, False)]


def test_a_github_phase_runs_in_its_clone_and_reports_it_once():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(
            tmp, phases=[("1", "First", GITHUB), ("2", "Second", GITHUB)])
        clone, _, patch = fake_clone(tmp)
        r = ScriptedLoop(slice_dir, [V["exec_done"], V["review_signoff"],
                                     V["exec_done"], V["review_signoff"],
                                     *TAIL], repo_root=repo)
        with patch:
            assert run_to_exit(r) == 0
            branch_ops = [root for root, c in r.fake_git.calls
                          if c[0] == "checkout"
                          and any("phase/074-P" in a for a in c)]
            assert branch_ops and all(str(root) == str(clone.resolve())
                                      for root in branch_ops)
            report = load_report(slice_dir)
            assert report.count(clone_headline(clone)) == 1
            # an event that describes no problem: the record, nothing asked
            record = report[report.index("\n## Record\n"):]
            assert f"### E1 — {clone_headline(clone)}\n" in record
            entry = next(e for e in json.loads(
                (slice_dir / "close-out.json").read_text())["entries"]
                if e["headline"] == clone_headline(clone))
            assert entry["kind"] == "event" and entry["proposal"] is None
            assert entry["labels"] == dict.fromkeys(
                ("trigger", "impact", "signal"), "none")
            assert entry["consequence"].startswith("none — the clone is where")
            assert (entry["evidence"], entry["author"]) == (
                "witnessed", "the driver's target resolution")
            body = " ".join(entry["body"])
            assert f"`Target: {GITHUB}`" in body
            assert ("The close-out session removes it then and says so under "
                    "this entry; nothing is asked of the operator.") in body
            assert load_state(slice_dir)["scratch_clones_reported"] == [
                str(clone.resolve())]
            assert run_loop.live_entries(slice_dir, "Outstanding actions") == []
            assert run_loop.open_prerun_actions(slice_dir) == []
            # a later run whose state lost the record finds the entry
            again = ScriptedLoop(slice_dir, [], repo_root=repo)
            again.state = {"bases": {}}
            again._report_scratch_clone(again._resolve_target(GITHUB))
            assert load_report(slice_dir).count(clone_headline(clone)) == 1


def test_a_github_phase_with_no_manifest_and_no_gate_ruling_is_refused():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp, phases=[("1", "First", GITHUB)])
        _, _, patch = fake_clone(tmp, manifest=False)
        r = ScriptedLoop(slice_dir, [], repo_root=repo)
        with patch:
            assert run_to_exit(r) == 4
            assert r.spawned == [], "nothing dispatched on an ungated clone"
            bail = json.loads((slice_dir / "bailout.json").read_text())
            assert bail["reason"] == "plan_doc" and bail["question"] is True
            assert "has no `.kubecoder/project.yaml`" in bail["details"]
            assert (f"`- gate {GITHUB} — <substitute or none> — <why>`"
                    in bail["details"])

            # the operator's gate ruling lifts it
            ruled_plan(slice_dir, f"gate {GITHUB} — none — no suite there",
                       body=phase_section("1", "First", GITHUB))
            r2 = ScriptedLoop(slice_dir, [V["exec_done"], V["review_signoff"],
                                          *TAIL], resume=True, repo_root=repo)
            assert run_to_exit(r2) == 0
            assert load_state(slice_dir)["phases"]["1"]["status"] == "merged"


def test_a_github_phase_that_adds_the_manifest_runs_gated_by_it():
    """`Creates:` on a GitHub Target whose clone has no manifest is the
    phase writing one: it runs with no gate ruling and is gated by what it
    wrote. One that did not write it is a phase nothing verifies, so the
    gate stops the run on the operator's question, as the check before the
    writer stops an undeclared one (AIWF-77)."""
    phases = [("1", "Bootstrap", GITHUB, False, "Creates: root\n")]
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp, phases=phases)
        clone, _, patch = fake_clone(tmp, manifest=False)
        writer = ("code-writer", {"outcome": "done", "summary": "built"},
                  adds_manifest(clone))
        r = ScriptedLoop(slice_dir, [writer, V["review_signoff"], *TAIL],
                         repo_root=repo)
        with patch:
            assert run_to_exit(r) == 0
        assert r.gate_calls == [("1", True)]
        assert r.gate_cwds == [clone.resolve()]
        assert load_state(slice_dir)["phases"]["1"]["status"] == "merged"
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp, phases=phases)
        _, _, patch = fake_clone(tmp, manifest=False)
        r = ScriptedLoop(slice_dir, [V["exec_done"]], repo_root=repo)
        with patch:
            assert run_to_exit(r) == 4
        assert [s[0] for s in r.spawned] == ["code-writer"]
        assert r.gate_calls == [], "nothing passed unverified"
        bail = json.loads((slice_dir / "bailout.json").read_text())
        assert (bail["reason"], bail["question"], bail["phase"]) == (
            "plan_doc", True, "1")
        assert "has no `.kubecoder/project.yaml`" in bail["details"]
    # the dry run reads the declaration the same way
    with tempfile.TemporaryDirectory() as tmp:
        code, out, err = dry_run_github(tmp, body="Creates: root\n")
    assert code is None, err
    assert "gate: kc project test (gated once P1 adds the manifest)" in out
    assert "is cloned at" not in err


def dry_run_github(tmp, *rulings, manifest=False, body=""):
    """(exit code or None, stdout, stderr) of a dry run over a one-phase
    plan targeting GITHUB, its phase's body `body`."""
    root = dry_run_repo(tmp)
    slice_dir, _ = make_slice(tmp, repo=False)
    ruled_plan(slice_dir, *rulings,
               body=phase_section("1", "X", GITHUB, body=body))
    _, _, patch = fake_clone(tmp, manifest=manifest)
    loop = RunLoop(slice_dir, resume=False)
    loop.repo_root = root
    out, err = io.StringIO(), io.StringIO()
    code = None
    with patch, contextlib.redirect_stdout(out), \
            contextlib.redirect_stderr(err):
        try:
            run_loop.cmd_dry_run(loop)
        except SystemExit as e:
            code = e.code
    return code, out.getvalue(), err.getvalue()


def test_a_dry_run_lists_an_ungated_github_target_as_a_plan_problem():
    with tempfile.TemporaryDirectory() as tmp:
        code, out, err = dry_run_github(tmp)
    assert code == 2
    assert f"target={GITHUB} [sibling]" in out
    assert "gate: (no deterministic gate)" in out
    assert f"phase P1: Target `{GITHUB}` is cloned at" in err
    assert f"`- gate {GITHUB} — <substitute or none> — <why>`" in err


def test_a_dry_run_passes_a_github_target_a_ruling_or_a_manifest_gates():
    with tempfile.TemporaryDirectory() as tmp:
        ruled = dry_run_github(tmp, f"gate {GITHUB} — none — no suite")
    with tempfile.TemporaryDirectory() as tmp:
        manifest = dry_run_github(tmp, manifest=True)
    assert ruled[0] is None, ruled[2]
    assert f"  ruling  gate {GITHUB}" in ruled[1]
    assert manifest[0] is None, manifest[2]
    assert "gate: kc project test" in manifest[1]


# -- tool containers: a Target repo's `cexec <tool>` against the pod (AIWF-24)
#
# FieldnotesApp slice 001's P6 gated FieldnotesDeploy from an environment
# without `aac-tools`: the code-writer handed back `blocked` after ten
# minutes, on a fix (config.yaml + `kc env restart`) that ends the session
# resuming the run. Ansible 033 bailed at the sweep on KubeCoder's missing
# `python`/`frontend`. The check asks the operator before any dispatch, and a
# gate that meets cexec's missing-tool line mid-run is never a red to fix.

CEXEC_MISSING = ('cexec: tool "aac-tools" is not available in this '
                 "environment; the tools it has are: python; if you just "
                 "added it to .kubecoder/config.yaml, run `kc env restart` "
                 "to apply it\n")
DEPLOY_MANIFEST = """\
projects:
  - name: root
    test: cexec aac-tools gen-architecture && cexec python pytest
"""
HOST_CONFIG = """\
repos:
  - url: https://example.invalid/Specs
tools:
  # the suites
  - use: python
{extra}
preamble:
  instructions: |
    use: not-a-tool
"""


def deploy_repo(tmp, manifest=DEPLOY_MANIFEST, name="Deploy"):
    """A sibling repo whose manifest calls `aac-tools`, a tool the suite's
    pod (RUNNING) does not run."""
    sib = make_sibling(tmp, name=name)
    (sib / ".kubecoder" / "project.yaml").write_text(manifest)
    return sib


def host_config(repo, *declared):
    (repo / ".kubecoder").mkdir(parents=True, exist_ok=True)
    (repo / ".kubecoder" / "config.yaml").write_text(HOST_CONFIG.format(
        extra="".join(f"  - use: {t}\n" for t in declared)))


def test_the_tool_scan_reads_calls_and_skips_guards_and_comments():
    text = """\
# test: cexec commented-out pytest
projects:
  - name: root
    test: cexec python uv run pytest
    build: ! cexec probe true || echo "no probe, skipped"
    lint: if cexec optional true; then cexec needed lint; fi
    deploy: if false; then :; elif cexec elsewhere true; then :; fi
    setup: true && cexec frontend npm ci; ! cexec probe2 true
    help: cexec --help
    gate: '! cexec go true 2>/dev/null || cexec go go test ./...'
    other: "! cexec probe3 true || cexec other run"
    next: ! cexec probe4 true; cexec probe4 run
    then: ! cexec probe5 true && cexec probe5 run
"""
    assert run_loop.manifest_tools(text) == {
        "python", "needed", "frontend", "other", "probe4", "probe5"}


def test_the_config_scan_reads_the_tools_list_alone():
    config = HOST_CONFIG.format(extra="  # comment\n  - use: \"aac-tools\"\n")
    assert run_loop.declared_tools(config) == {"python", "aac-tools"}
    assert run_loop.declared_tools("tools:\n- use: x\nother:\n- use: y\n") \
        == {"x"}


def test_missing_tools_name_each_tool_its_manifests_and_the_fix():
    with tempfile.TemporaryDirectory() as tmp:
        a = deploy_repo(tmp, name="Deploy")
        b = deploy_repo(tmp, name="KubeCoder", manifest=(
            "lint: cexec frontend npm run lint\n"
            "test: cexec aac-tools check\n"))
        host = Path(tmp) / "host"
        host_config(host, "frontend")
        missing = run_loop.missing_tools([a, b, Path(tmp) / "nomanifest"],
                                         host, {"python"})
        assert [(m.tool, m.callers, m.declared) for m in missing] == [
            ("aac-tools", ["Deploy/.kubecoder/project.yaml",
                           "KubeCoder/.kubecoder/project.yaml"], False),
            ("frontend", ["KubeCoder/.kubecoder/project.yaml"], True)]
        details = run_loop.missing_tools_details(missing, host)
        config = host / ".kubecoder" / "config.yaml"
        assert details.startswith("the run needs tool containers this "
                                  "environment does not run:\n")
        assert (f"- aac-tools — called by Deploy/.kubecoder/project.yaml, "
                f"KubeCoder/.kubecoder/project.yaml; add `- use: aac-tools` "
                f"under `tools:` in {config}, then `kc env restart`") \
            in details
        assert (f"- frontend — called by KubeCoder/.kubecoder/project.yaml; "
                f"declared in {config} but not running in this pod (it "
                "predates that commit) — `kc env restart` applies it") \
            in details
        assert "relaunch with --resume" in details


def test_a_describe_that_fails_passes_the_check_with_a_warning():
    with tempfile.TemporaryDirectory() as tmp:
        sib = deploy_repo(tmp)

        def broken():
            raise ValueError("`kc env describe --output=json` failed (rc=1)")

        logged = []
        with patched(run_loop, running_tools=broken):
            assert run_loop.tools_check([sib], [], Path(tmp),
                                        logged.append) is None
        assert logged and logged[0].startswith("warning: tool check skipped")
        # and the seam itself turns a kc that answers nonsense into the error
        bad = subprocess.CompletedProcess([], 0, stdout='{"name": "x"}',
                                          stderr="")
        with patched(run_loop.subprocess, run=lambda *a, **kw: bad):
            try:
                REAL_RUNNING_TOOLS()
            except ValueError as e:
                assert "no `sections` list" in str(e)
            else:
                raise AssertionError("no sections must be a ValueError")
        good = subprocess.CompletedProcess(
            [], 0, stdout=json.dumps({"sections": [
                {"name": "python", "instructions": "", "ports": []}]}),
            stderr="")
        with patched(run_loop.subprocess, run=lambda *a, **kw: good):
            assert REAL_RUNNING_TOOLS() == {"python"}


def tools_run(tmp, *, rulings=(), declared=(), resume=False, script=None):
    """A run whose one phase targets `../Deploy` (whose manifest calls
    `aac-tools`), from a host repo whose config declares `declared`."""
    deploy_repo(tmp)
    slice_dir, repo = make_slice(tmp)
    host_config(repo, *declared)
    body = phase_section("1", "Deploy change", "../Deploy")
    if rulings:
        ruled_plan(slice_dir, *rulings, body=body)
    else:
        (slice_dir / "plan.md").write_text("# plan\n\n" + body)
    r = ScriptedLoop(slice_dir, script or [], repo_root=repo, resume=resume)
    return slice_dir, repo, r


def test_a_target_calling_a_missing_tool_bails_before_any_dispatch():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo, r = tools_run(tmp)
        assert run_to_exit(r) == 4
        assert not r.spawned
        bail = json.loads((slice_dir / "bailout.json").read_text())
        assert bail["reason"] == "missing_tools" and bail["question"] is True
        details = bail["details"]
        assert "- aac-tools — called by Deploy/.kubecoder/project.yaml" \
            in details
        assert "add `- use: aac-tools` under `tools:` in " \
            f"{repo / '.kubecoder' / 'config.yaml'}" in details
        assert "python" not in details.split("\n")[1]
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo, r = tools_run(tmp, declared=["aac-tools"])
        assert run_to_exit(r) == 4
        details = json.loads((slice_dir / "bailout.json").read_text())[
            "details"]
        assert "declared in" in details and "not running in this pod" \
            in details
        assert "`kc env restart` applies it" in details
        assert "add `- use:" not in details


def test_a_resume_runs_the_tool_check_too():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo, r = tools_run(tmp)
        assert run_to_exit(r) == 4
        r2 = ScriptedLoop(slice_dir, [], repo_root=repo, resume=True)
        assert run_to_exit(r2) == 4 and not r2.spawned
        assert json.loads((slice_dir / "bailout.json").read_text())[
            "reason"] == "missing_tools"
        # once the pod runs it, the resume proceeds
        r3 = ScriptedLoop(slice_dir, [V["exec_done"], V["review_signoff"],
                                      *TAIL], repo_root=repo, resume=True)
        with patched(run_loop, running_tools=lambda: {"python",
                                                      "aac-tools"}):
            assert run_to_exit(r3) == 0
        assert not r3.script


def test_a_resume_checks_the_repos_the_run_already_touched():
    """No pending phase targets the repo any more, but the run's `bases`
    hold it — the loop-tail sweep would run its gates."""
    with tempfile.TemporaryDirectory() as tmp:
        sib = deploy_repo(tmp)
        slice_dir, repo = make_slice(tmp)
        (slice_dir / "plan.md").write_text(
            "# plan\n\n" + phase_section("1", "Done", "../Deploy", done=True)
            + "\n" + phase_section("2", "App change"))
        r = ScriptedLoop(slice_dir, [], repo_root=repo)
        r.state = {"bases": {str(sib): "main"}}
        assert sib.resolve() in [Path(p).resolve() for p in r._tool_roots()]
        assert "aac-tools" in (r._missing_tools() or "")


def test_rulings_waiving_every_gate_of_the_repo_let_the_run_proceed():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo, r = tools_run(tmp, rulings=(
            "gate ../Deploy — none — no aac-tools in this environment",
            "accept ../Deploy lint — no aac-tools in this environment",
            "accept ../Deploy build — no aac-tools in this environment"),
            script=[V["exec_done"], V["review_signoff"], *TAIL])
        assert run_to_exit(r) == 0
        assert not r.script
    # one verb left unwaived still holds the repo to its tools
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo, r = tools_run(tmp, rulings=(
            "gate ../Deploy — none — no aac-tools in this environment",
            "accept ../Deploy lint — no aac-tools in this environment"))
        assert run_to_exit(r) == 4
        assert json.loads((slice_dir / "bailout.json").read_text())[
            "reason"] == "missing_tools"


def test_a_dry_run_lists_the_missing_tools_as_a_plan_problem():
    with tempfile.TemporaryDirectory() as tmp:
        deploy_repo(tmp)
        root = dry_run_repo(tmp)
        slice_dir, _ = make_slice(tmp, repo=False)
        (slice_dir / "plan.md").write_text(
            "# plan\n\n" + phase_section("1", "Deploy change", "../Deploy"))
        code, out, err = dry_run_from(RunLoop(slice_dir, resume=False), root)
        assert code == 2
        assert "plan problems:" in err
        assert "the run needs tool containers this environment does not run"\
            in err
        assert "- aac-tools — called by Deploy/.kubecoder/project.yaml" in err


class MissingToolLoop(KcExitLoop):
    """KcExitLoop whose red kc runs print cexec's missing-tool line."""

    def _gate_exec(self, argv, cwd, log_file):
        rc_ = super()._gate_exec(argv, cwd, log_file)
        if rc_ == 1:
            log_file.write(CEXEC_MISSING)
        return rc_


def test_a_sweep_row_that_meets_a_missing_tool_is_unrunnable_not_red():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r = MissingToolLoop(slice_dir, [V["exec_done"], V["review_signoff"],
                                        *TAIL],
                            repo_root=repo,
                            sweep_rcs={(PROJECT, "build"): 1})
        assert run_to_exit(r) == 0
        sweep = load_state(slice_dir)["gate_sweep"]
        build = next(row for row in sweep["results"]
                     if row["verb"] == "build")
        assert build["outcome"] == "unrunnable" and build["green"] is False
        assert build["tool"] == "aac-tools"
        assert sweep["outcome"] == "green"
        # nothing else ran green: the sweep proved nothing, never red
        block = r._sweep_block(
            {**sweep, "results": [build]}, "GREEN-STANCE", "RED-STANCE")
        assert run_loop.SWEEP_STANCE_NONE in block
        assert "RED-STANCE" not in block
        consult = next(p for role, p in r.prompts if role == "consult")
        assert (f"{PROJECT} build → UNRUNNABLE (tool missing) — cexec tool "
                "`aac-tools` is not in this environment") in consult
        assert "An UNRUNNABLE row did not run" in consult
        row = next(h for h in load_state(slice_dir)["history"]
                   if h["role"] == "sweep")
        assert "1 unrunnable — tool missing" in row["summary"]


def test_a_phase_gate_that_meets_a_missing_tool_bails_without_a_fix_round():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r = MissingToolLoop(slice_dir, [V["exec_done"]], repo_root=repo,
                            gate_rcs=[1])
        assert run_to_exit(r) == 4
        assert not r.script and len(r.spawned) == 1, "no fix round"
        bail = json.loads((slice_dir / "bailout.json").read_text())
        assert bail["reason"] == "missing_tools" and bail["question"]
        assert bail["phase"] == "1"
        assert "- aac-tools — called by `kc project test --project app` in " \
            "repo" in bail["details"]
        assert "add `- use: aac-tools`" in bail["details"]
        assert load_state(slice_dir)["phases"]["1"]["gate_fix_rounds"] == 0


class MissingToolFullOutputLoop(KcFullOutputLoop, MissingToolLoop):
    """A red kc run printing cexec's missing-tool line, then kc's pointer."""


def test_a_missing_tool_bailout_still_inlines_kcs_full_output():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        full = kc_full_log(tmp, "test-missing.log", "FULL-OF-THE-RED-RUN\n")
        r = MissingToolFullOutputLoop(slice_dir, [V["exec_done"]],
                                      repo_root=repo, gate_rcs=[1],
                                      full_outputs=[full])
        assert run_to_exit(r) == 4
        bail = json.loads((slice_dir / "bailout.json").read_text())
        assert bail["reason"] == "missing_tools"
        log = (slice_dir / "phases" / "P1" / "gate_r1.log").read_text()
        assert log.index(CEXEC_MISSING) < log.index(
            f"=== kc's full output ({full}) ===\nFULL-OF-THE-RED-RUN\n")


def test_a_doc_gate_command_that_meets_a_missing_tool_is_unrunnable():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        loop = RunLoop(slice_dir, resume=False)
        loop.repo_root = repo
        loop.state = {"history": []}
        calls = []

        def fake_exec(argv, log_file):
            calls.append(argv[2])
            if argv[2] == "lint":
                log_file.write(CEXEC_MISSING)
                return 1
            # a later red that is not the tool's is still red
            log_file.write("ordinary failure\n")
            return 1 if argv[2] == "test" else 0

        loop._doc_gate_exec = fake_exec
        passed, log_path = loop._run_doc_gate({"gate_runs": 0})
        assert calls == ["lint", "build", "test"], "lint was not fail-fast"
        assert not passed
        text = log_path.read_text()
        assert "→ UNRUNNABLE: cexec tool `aac-tools`" in text
        calls.clear()

        def only_the_tool(argv, log_file):
            calls.append(argv[2])
            if argv[2] != "lint":
                return 0
            log_file.write(CEXEC_MISSING)
            return 1

        loop._doc_gate_exec = only_the_tool
        passed, _ = loop._run_doc_gate({"gate_runs": 1})
        assert passed and calls == ["lint", "build", "test"]
        assert loop.state["history"][-1]["outcome"] == "green"


# -- services: a Target repo's config.yaml `services:` against the pod (AIWF-38)
#
# Ansible slice 036's P14 targeted ElectronicsInventory from the Ansible
# environment, which runs no postgres or s3storage: setup and tests failed on
# localhost:5432 and :9000, and the driver dispatched a fix round that could
# only hand back `blocked`. A red gate in a repo whose services the pod lacks
# is never a red to fix. Before any dispatch only the host's own are asked
# (AIWF-75): KubeCoder slice 244 stopped in planning over a service Ansible's
# config declares for a phase whose gates never touch it, so another Target
# repo's are a warning.

INVENTORY_CONFIG = """\
# services:
#   - commented-out
tools:
  - use: python
services:
  # the suites' database
  - postgres
  - use: s3storage
    expose: [9000]
preamble:
  instructions: |
    - not-a-service
"""


def inventory_repo(tmp, config=INVENTORY_CONFIG, name="Inventory"):
    """A sibling repo whose environment config declares `postgres` and
    `s3storage`, services the suite's pod (RUNNING_SERVICES) does not run."""
    sib = make_sibling(tmp, name=name)
    (sib / ".kubecoder" / "config.yaml").write_text(config)
    return sib


def host_services(repo, *declared):
    (repo / ".kubecoder").mkdir(parents=True, exist_ok=True)
    (repo / ".kubecoder" / "config.yaml").write_text(
        "tools:\n  - use: python\nservices:\n"
        + "".join(f"  - {s}\n" for s in declared))


def test_the_config_scan_reads_the_services_list_both_forms():
    assert run_loop.config_services(INVENTORY_CONFIG) == {"postgres",
                                                          "s3storage"}
    text = """\
services:
  - 'redis'  # quoted, a comment after
  - use: "minio"
    expose: [9000]
  - expose: [8080]
    use: keycloak
other:
  - stray
"""
    assert run_loop.config_services(text) == {"redis", "minio", "keycloak"}
    # the tools list is no services list, and the other way round
    assert run_loop.config_services(HOST_CONFIG.format(extra="")) == set()
    assert run_loop.declared_tools(INVENTORY_CONFIG) == {"python"}


def test_missing_services_name_each_service_its_configs_and_the_fix():
    with tempfile.TemporaryDirectory() as tmp:
        a = inventory_repo(tmp)
        b = inventory_repo(tmp, name="Shop",
                           config="services:\n  - postgres\n  - redis\n")
        host = Path(tmp) / "host"
        host_services(host, "redis")
        # the host is a root too: its own unrun service is a restart owed
        missing = run_loop.missing_services(
            [a, b, host, Path(tmp) / "noconfig"], host, {"s3storage"})
        assert [(m.service, m.callers, m.declared) for m in missing] == [
            ("postgres", ["Inventory/.kubecoder/config.yaml",
                          "Shop/.kubecoder/config.yaml"], False),
            ("redis", ["Shop/.kubecoder/config.yaml",
                       "host/.kubecoder/config.yaml"], True)]
        details = run_loop.missing_services_details(missing, host)
        config = host / ".kubecoder" / "config.yaml"
        assert details.startswith("the run needs services this environment "
                                  "does not run:\n")
        assert (f"- postgres — declared by Inventory/.kubecoder/config.yaml, "
                f"Shop/.kubecoder/config.yaml; add `- postgres` under "
                f"`services:` in {config}, then `kc env restart`") in details
        assert (f"- redis — declared by Shop/.kubecoder/config.yaml, "
                f"host/.kubecoder/config.yaml; declared in {config} but not "
                "running in this pod (it predates that commit) — `kc env "
                "restart` applies it") in details
        assert "relaunch with --resume" in details
        assert "waive the repo's gates" in details


def test_a_describe_that_fails_passes_the_service_check_with_a_warning():
    with tempfile.TemporaryDirectory() as tmp:
        sib = inventory_repo(tmp)

        def broken():
            raise ValueError("`kc env describe --output=json` failed (rc=1)")

        logged = []
        with patched(run_loop, running_services=broken):
            assert run_loop.services_check([sib], [], Path(tmp),
                                           logged.append) is None
            assert logged and logged[0].startswith(
                "warning: service check skipped")
            # a repo whose config declares no service asks kc nothing
            logged.clear()
            plain = make_sibling(tmp, name="Plain")
            assert run_loop.services_check([plain], [], Path(tmp),
                                           logged.append) is None
            assert not logged
        # the seam: describe's top-level `services`, by name, state unread
        bad = subprocess.CompletedProcess(
            [], 0, stdout=json.dumps({"sections": []}), stderr="")
        with patched(run_loop.subprocess, run=lambda *a, **kw: bad):
            try:
                REAL_RUNNING_SERVICES()
            except ValueError as e:
                assert "no `services` list" in str(e)
            else:
                raise AssertionError("no services must be a ValueError")
        good = subprocess.CompletedProcess([], 0, stdout=json.dumps({
            "sections": [{"name": "python", "instructions": "", "ports": []}],
            "services": [{"name": "postgres", "state": "running"},
                         {"name": "s3storage", "state": "pending"}]}),
            stderr="")
        with patched(run_loop.subprocess, run=lambda *a, **kw: good):
            assert REAL_RUNNING_SERVICES() == {"postgres", "s3storage"}
            assert REAL_RUNNING_TOOLS() == {"python"}
        none = subprocess.CompletedProcess(
            [], 0, stdout=json.dumps({"sections": [], "services": []}),
            stderr="")
        with patched(run_loop.subprocess, run=lambda *a, **kw: none):
            assert REAL_RUNNING_SERVICES() == set()


def services_run(tmp, *, target="../Inventory", rulings=(), declared=(),
                 resume=False, script=None):
    """A run whose one phase targets `target` — `../Inventory` (whose config
    declares `postgres` and `s3storage`) unless the test names another — from
    a host repo whose config declares `declared`."""
    inventory_repo(tmp)
    slice_dir, repo = make_slice(tmp)
    host_services(repo, *declared)
    body = phase_section("1", "The change", target)
    if rulings:
        ruled_plan(slice_dir, *rulings, body=body)
    else:
        (slice_dir / "plan.md").write_text("# plan\n\n" + body)
    r = ScriptedLoop(slice_dir, script or [], repo_root=repo, resume=resume)
    return slice_dir, repo, r


# A run's whole script: the one phase, then the tail.
SERVICES_SCRIPT = [V["exec_done"], V["review_signoff"], *TAIL]
NOT_HELD = ("warning: services not held — Inventory/.kubecoder/config.yaml "
            "declares postgres, s3storage, which this pod does not run; only "
            "the host's own are held, and a gate that goes red in Inventory "
            "bails missing_services")


def test_a_sibling_target_needing_a_missing_service_is_warned_about_not_held():
    """KubeCoder slice 244: another repo's config declares services for its
    own workspace, and nothing says which its gates use."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo, r = services_run(tmp, script=SERVICES_SCRIPT)
        assert run_to_exit(r) == 0
        assert not r.script
        assert NOT_HELD in (slice_dir / "log.txt").read_text()


def test_a_host_declaring_a_missing_service_bails_before_any_dispatch():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo, r = services_run(tmp, target=PROJECT,
                                          declared=["postgres"])
        assert run_to_exit(r) == 4
        assert not r.spawned
        bail = json.loads((slice_dir / "bailout.json").read_text())
        assert bail["reason"] == "missing_services" and bail["question"] is True
        details = bail["details"]
        config = repo / ".kubecoder" / "config.yaml"
        assert ("- postgres — declared by repo/.kubecoder/config.yaml; "
                f"declared in {config} but not running in this pod") in details
        assert "`kc env restart` applies it" in details
        assert "add `- " not in details
        # the sibling's are no part of it
        assert "s3storage" not in details


def test_a_resume_runs_the_service_check_too():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo, r = services_run(tmp, target=PROJECT,
                                          declared=["postgres"])
        assert run_to_exit(r) == 4
        r2 = ScriptedLoop(slice_dir, [], repo_root=repo, resume=True)
        assert run_to_exit(r2) == 4 and not r2.spawned
        assert json.loads((slice_dir / "bailout.json").read_text())[
            "reason"] == "missing_services"
        # once the pod runs it, the resume proceeds
        r3 = ScriptedLoop(slice_dir, list(SERVICES_SCRIPT), repo_root=repo,
                          resume=True)
        with patched(run_loop, running_services=lambda: {"postgres"}):
            assert run_to_exit(r3) == 0
        assert not r3.script


def test_a_sibling_the_run_already_touched_is_warned_about_not_held():
    """No pending phase targets the repo any more, but the run's `bases`
    hold it — the loop-tail sweep would run its suites, and a red there is
    where its services are asked."""
    with tempfile.TemporaryDirectory() as tmp:
        sib = inventory_repo(tmp)
        slice_dir, repo = make_slice(tmp)
        (slice_dir / "plan.md").write_text(
            "# plan\n\n"
            + phase_section("1", "Done", "../Inventory", done=True)
            + "\n" + phase_section("2", "App change"))
        r = ScriptedLoop(slice_dir, [], repo_root=repo)
        r.state = {"bases": {str(sib): "main"}}
        logged = []
        r.log = logged.append
        assert r._missing_services() is None
        assert logged == [NOT_HELD]


HOST_WAIVERS = (
    f"gate {PROJECT} — none — no postgres in this environment",
    f"accept {PROJECT} lint — no postgres in this environment",
    f"accept {PROJECT} build — no postgres in this environment")


def test_rulings_waiving_every_gate_of_the_host_exempt_it_from_its_services():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo, r = services_run(
            tmp, target=PROJECT, declared=["postgres"], rulings=HOST_WAIVERS,
            script=SERVICES_SCRIPT)
        assert run_to_exit(r) == 0
        assert not r.script
    # one verb left unwaived still holds the host to its services
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo, r = services_run(
            tmp, target=PROJECT, declared=["postgres"],
            rulings=HOST_WAIVERS[:2])
        assert run_to_exit(r) == 4
        assert json.loads((slice_dir / "bailout.json").read_text())[
            "reason"] == "missing_services"


def test_a_sibling_the_rulings_waive_whole_is_not_warned_about():
    """Nothing runs its suites, so there is nothing to warn of."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo, r = services_run(tmp, rulings=(
            "gate ../Inventory — none — no postgres in this environment",
            "accept ../Inventory lint — no postgres in this environment",
            "accept ../Inventory build — no postgres in this environment"),
            script=SERVICES_SCRIPT)
        assert run_to_exit(r) == 0
        assert not r.script
        assert "services not held" not in (slice_dir / "log.txt").read_text()


def test_a_dry_run_warns_once_of_a_siblings_unheld_services():
    with tempfile.TemporaryDirectory() as tmp:
        inventory_repo(tmp)
        root = dry_run_repo(tmp)
        slice_dir, _ = make_slice(tmp, repo=False)
        (slice_dir / "plan.md").write_text(
            "# plan\n\n"
            + phase_section("1", "Inventory change", "../Inventory"))
        code, out, err = dry_run_from(RunLoop(slice_dir, resume=False), root)
        assert code == 0, err
        assert err.count("warning: services not held — ") == 1, err
        assert f"{NOT_HELD}\n" in err
        assert "warning: warning:" not in err
        assert "plan problems:" not in err


def test_a_dry_run_lists_the_hosts_missing_services_as_a_plan_problem():
    with tempfile.TemporaryDirectory() as tmp:
        root = dry_run_repo(tmp)
        host_services(root, "postgres")
        slice_dir, _ = make_slice(tmp, repo=False)
        (slice_dir / "plan.md").write_text(
            "# plan\n\n" + phase_section("1", "App change"))
        code, out, err = dry_run_from(RunLoop(slice_dir, resume=False), root)
        assert code == 2
        assert "plan problems:" in err
        assert "the run needs services this environment does not run" in err
        assert "- postgres — declared by repo/.kubecoder/config.yaml" in err


def declares_services(*services):
    """A code-writer effect: the phase adds `services` to the repo's
    environment config — after the startup check, as a phase that brings a
    database in does."""
    def effect(loop):
        host_services(loop.repo_root, *services)
    return effect


def test_a_red_gate_in_a_repo_missing_its_services_bails_without_a_fix_round():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r = KcExitLoop(slice_dir,
                       [(*V["exec_done"], declares_services("postgres"))],
                       repo_root=repo, gate_rcs=[1])
        assert run_to_exit(r) == 4
        assert not r.script and len(r.spawned) == 1, "no fix round"
        bail = json.loads((slice_dir / "bailout.json").read_text())
        assert bail["reason"] == "missing_services" and bail["question"]
        assert bail["phase"] == "1"
        details = bail["details"]
        assert (f"`kc project test --project {PROJECT}` in repo went red "
                "(output in ") in details
        assert "gate_r1.log), and the repo declares services this pod " \
            "does not run" in details
        config = repo / ".kubecoder" / "config.yaml"
        assert ("- postgres — declared by repo/.kubecoder/config.yaml; "
                f"declared in {config} but not running in this pod") \
            in details
        assert load_state(slice_dir)["phases"]["1"]["gate_fix_rounds"] == 0


def test_a_red_gate_in_a_sibling_missing_its_services_bails_too():
    """The startup check only warns of a sibling's services; a gate gone red
    there is where they are asked."""
    with tempfile.TemporaryDirectory() as tmp:
        inventory_repo(tmp)
        slice_dir, repo = make_slice(tmp)
        (slice_dir / "plan.md").write_text(
            "# plan\n\n"
            + phase_section("1", "Inventory change", "../Inventory"))
        r = KcExitLoop(slice_dir, [V["exec_done"]], repo_root=repo,
                       gate_rcs=[1])
        assert run_to_exit(r) == 4
        assert not r.script and len(r.spawned) == 1, "no fix round"
        assert NOT_HELD in (slice_dir / "log.txt").read_text()
        bail = json.loads((slice_dir / "bailout.json").read_text())
        assert bail["reason"] == "missing_services" and bail["question"]
        assert bail["phase"] == "1"
        details = bail["details"]
        assert " in Inventory went red (output in " in details
        assert "and the repo declares services this pod does not run" \
            in details
        config = repo / ".kubecoder" / "config.yaml"
        assert ("- postgres — declared by Inventory/.kubecoder/config.yaml; "
                f"add `- postgres` under `services:` in {config}") in details
        assert "- s3storage — declared by Inventory/.kubecoder/config.yaml" \
            in details
        assert load_state(slice_dir)["phases"]["1"]["gate_fix_rounds"] == 0


def test_a_red_gate_in_a_repo_whose_services_all_run_gets_its_fix_round():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        host_services(repo, "postgres")
        r = KcExitLoop(slice_dir, [V["exec_done"], V["exec_done"],
                                   V["review_signoff"], *TAIL],
                       repo_root=repo, gate_rcs=[1, 0])
        with patched(run_loop, running_services=lambda: {"postgres"}):
            assert run_to_exit(r) == 0
        assert not r.script
        assert load_state(slice_dir)["phases"]["1"]["gate_fix_rounds"] == 1
    # kc that cannot say which services run leaves the red a red: a
    # warning, and the fix round
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r = KcExitLoop(slice_dir,
                       [(*V["exec_done"], declares_services("postgres")),
                        V["exec_done"], V["review_signoff"], *TAIL],
                       repo_root=repo, gate_rcs=[1, 0])

        def broken():
            raise ValueError("`kc env describe --output=json` failed (rc=1)")

        with patched(run_loop, running_services=broken):
            assert run_to_exit(r) == 0
        assert not r.script
        assert load_state(slice_dir)["phases"]["1"]["gate_fix_rounds"] == 1
        assert "warning: service check of a red gate skipped" \
            in (slice_dir / "log.txt").read_text()


# -- the run-start setup -------------------------------------------------------
#
# A gate that fails on install state (a sibling never set up, a venv behind
# its lockfile) sent executors into fix rounds on code that was fine; the
# driver runs `kc project setup` in each repo the run needs before the first
# dispatch, and the gate still decides.

SETUP_ARGV = ["kc", "project", "setup"]


def test_setup_runs_once_per_target_repo_with_a_manifest_before_any_dispatch():
    """Two phases on one repo set it up once; a sibling without a manifest
    has nothing to set up. Bare `kc project setup`, from each repo's root,
    with the output under the slice's setup/."""
    with tempfile.TemporaryDirectory() as tmp:
        sib = make_sibling(tmp)
        make_sibling(tmp, name="Bare", manifest=False)
        slice_dir, repo = make_slice(tmp, phases=[
            ("1", "App change"), ("2", "Sibling change", "../Sibling"),
            ("3", "More app"), ("4", "Bare change", "../Bare")])
        r = ScriptedLoop(slice_dir, [V["exec_done"], V["review_signoff"]] * 4
                         + TAIL, repo_root=repo)
        assert run_to_exit(r) == 0
        assert not r.script
        assert r.setup_runs == [(SETUP_ARGV, repo.resolve(), 0),
                                (SETUP_ARGV, sib.resolve(), 0)]
        assert (slice_dir / "setup" / "Sibling.log").read_text() == \
            "kc project setup: exit 0\n"
        log = (slice_dir / "log.txt").read_text()
        assert "[setup] repo → GREEN (" in log
        assert "[setup] Sibling → GREEN (" in log


def test_a_red_hung_or_unstartable_setup_warns_and_the_run_goes_on():
    """The phase gate decides, so no setup outcome bails; exit 3 is a repo
    that defines no setup, and passes without a warning."""
    cases = [(1, "warning: [setup] repo → RED (exit 1, "),
             (2, "warning: [setup] repo → RED (exit 2, "),
             (subprocess.TimeoutExpired("kc", 900),
              "warning: [setup] repo timed out after 900s (output in "),
             (FileNotFoundError("no kc"),
              "warning: [setup] repo: `kc project setup` could not run"),
             (3, "[setup] repo → nothing ran (")]
    for setup, line in cases:
        with tempfile.TemporaryDirectory() as tmp:
            slice_dir, repo = make_slice(tmp)
            r = ScriptedLoop(slice_dir, [V["exec_done"], V["review_signoff"],
                                         *TAIL],
                             repo_root=repo, setup_rcs=[setup])
            assert run_to_exit(r) == 0, setup
            assert not r.script and len(r.setup_runs) == 1
            log = (slice_dir / "log.txt").read_text()
            assert line in log, (setup, log)
            assert ("warning: [setup]" in log) == (setup != 3)


def test_a_resume_runs_setup_again():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r = ScriptedLoop(slice_dir, [("code-writer", {"outcome": "blocked",
                                                       "summary": "no creds"})],
                         repo_root=repo)
        assert run_to_exit(r) == 3
        assert r.setup_runs == [(SETUP_ARGV, repo.resolve(), 0)]
        r2 = ScriptedLoop(slice_dir, [V["exec_done"], V["review_signoff"],
                                      *TAIL], resume=True, repo_root=repo)
        assert run_to_exit(r2) == 0
        assert r2.setup_runs == [(SETUP_ARGV, repo.resolve(), 0)]


def test_a_run_that_bails_on_missing_tools_runs_no_setup():
    with tempfile.TemporaryDirectory() as tmp:
        _, _, r = tools_run(tmp)
        assert run_to_exit(r) == 4
        assert r.setup_runs == []


def test_a_run_that_bails_on_missing_services_runs_no_setup():
    with tempfile.TemporaryDirectory() as tmp:
        _, _, r = services_run(tmp, target=PROJECT, declared=["postgres"])
        assert run_to_exit(r) == 4
        assert r.setup_runs == []


# -- the detached driver: the exit record, wait, stop, the handshake ---------
#
# `run --detach` leaves no process to report an exit code to, so the run puts
# it in state.json; `wait` reads that against the run.lock flock, and `stop`
# interrupts the driver the lock's note names. Tested against real files, a
# real flock and real child processes — never a real run's sessions.

def exit_record(slice_dir):
    return load_state(slice_dir).get("exit")


def test_every_exit_goes_on_record_in_state_json_last():
    def interrupt(loop):
        raise KeyboardInterrupt

    def crash(loop):
        raise RuntimeError("unexpected")

    cases = [
        ([V["exec_done"], V["review_signoff"], *TAIL], 0),
        ([("code-writer", {"outcome": "blocked", "summary": "broken"})], 3),
        ([("code-writer", {"outcome": "question", "summary": "which?"})], 4),
        ([(*V["exec_done"], interrupt)], 130),
    ]
    for script, code in cases:
        with tempfile.TemporaryDirectory() as tmp:
            slice_dir, repo = make_slice(tmp)
            r = ScriptedLoop(slice_dir, script, repo_root=repo)
            with contextlib.redirect_stderr(io.StringIO()), \
                    contextlib.redirect_stdout(io.StringIO()):
                assert run_to_exit(r) == code
            record = exit_record(slice_dir)
            assert record["code"] == code, (code, record)
            assert datetime.fromisoformat(record["ts"])
            if code in (3, 4):
                # written after bailout.json, never before it
                bail = slice_dir / "bailout.json"
                assert bail.stat().st_mtime_ns <= \
                    (slice_dir / "state.json").stat().st_mtime_ns
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r = ScriptedLoop(slice_dir, [(*V["exec_done"], crash)],
                         repo_root=repo)
        try:
            r.run()
        except RuntimeError:
            pass
        else:
            raise AssertionError("the crash did not propagate")
        assert exit_record(slice_dir)["code"] == 1
        # the lock is let go whatever the exit
        assert not run_loop.lock_held(slice_dir / "run.lock")


def test_a_fresh_run_refused_at_preflight_writes_no_state():
    """A refused fresh run that wrote a state.json would make the next
    attempt a --resume of a run that never started."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r = ScriptedLoop(slice_dir, [], repo_root=repo)
        r.fake_git.dirty = " M src/app.py"
        started = []
        r.on_start = lambda: started.append(True)
        with contextlib.redirect_stderr(io.StringIO()):
            assert run_to_exit(r) == 2
        assert not (slice_dir / "state.json").exists()
        assert not started


def test_a_second_fresh_run_is_refused_before_the_start_and_off_the_record():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        script = [("code-writer", {"outcome": "blocked", "summary": "x"})]
        with contextlib.redirect_stderr(io.StringIO()):
            assert run_to_exit(ScriptedLoop(slice_dir, script,
                                            repo_root=repo)) == 3
        before = (slice_dir / "state.json").read_text()
        again = ScriptedLoop(slice_dir, [], repo_root=repo)
        started = []
        again.on_start = lambda: started.append(True)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            assert run_to_exit(again) == 2
        assert "Pass --resume" in err.getvalue()
        assert not started
        # the refusal is not this state's run: its exit record stands
        assert (slice_dir / "state.json").read_text() == before


def test_the_start_point_is_reached_once_before_the_first_dispatch():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        seen = []

        def check(loop):
            seen.append("dispatched")

        r = ScriptedLoop(slice_dir, [(*V["exec_done"], check),
                                     V["review_signoff"], *TAIL],
                         repo_root=repo)
        r.on_start = lambda: seen.append("started")
        assert run_to_exit(r) == 0
        assert seen == ["started", "dispatched"]


def test_a_resume_clears_the_exit_record_before_anything_else():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        script = [("code-writer", {"outcome": "blocked", "summary": "x"})]
        with contextlib.redirect_stderr(io.StringIO()):
            assert run_to_exit(ScriptedLoop(slice_dir, script,
                                            repo_root=repo)) == 3
        assert exit_record(slice_dir)["code"] == 3
        on_disk = []

        def look(loop):
            on_disk.append(load_state(slice_dir).get("exit"))

        r = ScriptedLoop(slice_dir, [], resume=True, repo_root=repo)
        r.on_start = lambda: look(r)
        r.script = [(*V["exec_done"], look), V["review_signoff"], *TAIL]
        assert run_to_exit(r) == 0
        assert on_disk == [None, None]
        assert exit_record(slice_dir)["code"] == 0
        assert "killed from outside" not in (slice_dir / "log.txt").read_text()


def test_a_resume_logs_a_driver_killed_from_outside():
    """A clean release truncates the holder note, so a note on a free lock
    with no exit record is a driver that died holding the lock."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        script = [("code-writer", {"outcome": "blocked", "summary": "x"})]
        with contextlib.redirect_stderr(io.StringIO()):
            assert run_to_exit(ScriptedLoop(slice_dir, script,
                                            repo_root=repo)) == 3
        assert (slice_dir / "run.lock").read_text() == ""
        state = load_state(slice_dir)
        del state["exit"]
        (slice_dir / "state.json").write_text(json.dumps(state))
        (slice_dir / "run.lock").write_text(
            "host: pod\npid: 4242\nstarted: 2026-10-01T03:00:00+00:00\n")
        r = ScriptedLoop(slice_dir, [V["exec_done"], V["review_signoff"],
                                     *TAIL], resume=True, repo_root=repo)
        assert run_to_exit(r) == 0
        log = (slice_dir / "log.txt").read_text()
        assert ("the previous driver (pid 4242, started "
                "2026-10-01T03:00:00+00:00) left no exit record: killed "
                "from outside") in log
        # the note is this driver's now, and released clean
        assert (slice_dir / "run.lock").read_text() == ""


def test_the_slice_lock_keeps_the_note_it_found():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "run.lock"
        path.write_text("host: h\npid: 7\nstarted: then\n" + "x" * 200)
        lock = run_loop.SliceLock(path)
        assert lock.acquire() is None
        assert lock.previous_note.startswith("host: h\npid: 7")
        # the new note starts at byte 0 — no hole where the old one was
        assert path.read_text().startswith("environment: ")
        assert f"pid: {os.getpid()}" in path.read_text()
        assert "\0" not in path.read_text()
        assert "x" * 20 not in path.read_text()   # the old note's tail is cut
        lock.release()
        assert path.read_text() == ""


@contextlib.contextmanager
def environment_id(value):
    """The pod's KUBECODER_ENVIRONMENT_ID for the block; None unsets it."""
    saved = os.environ.pop("KUBECODER_ENVIRONMENT_ID", None)
    if value is not None:
        os.environ["KUBECODER_ENVIRONMENT_ID"] = value
    try:
        yield
    finally:
        os.environ.pop("KUBECODER_ENVIRONMENT_ID", None)
        if saved is not None:
            os.environ["KUBECODER_ENVIRONMENT_ID"] = saved


def test_the_slice_lock_note_names_the_environment_the_driver_runs_in():
    """A project's environments share the spec repo's mount, and the flock
    with it, but not their process tables: the note names the environment
    to look in, and the driver record the loops keep says the same."""
    host = run_loop.socket.gethostname()
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "run.lock"
        lock = run_loop.SliceLock(path)
        with environment_id("env-a"), \
                patched(run_loop, _heartbeat_stamp=lambda: "beat-0"):
            assert lock.acquire() is None
        try:
            note = path.read_text()
            assert [line.partition(":")[0] for line in note.splitlines()] \
                == ["environment", "host", "pid", "started", "heartbeat"]
            fields = run_loop.note_fields(note)
            assert fields["environment"] == "env-a"
            assert fields["host"] == host
            assert fields["pid"] == str(os.getpid())
            assert fields["heartbeat"] == "beat-0"
            assert datetime.fromisoformat(fields["started"])
            assert lock.driver == {"environment": "env-a", "host": host,
                                   "pid": os.getpid(),
                                   "started": fields["started"]}
        finally:
            lock.release()
        # Outside KubeCoder the note says so, and the record holds no id.
        for unset in (None, ""):
            with environment_id(unset):
                assert lock.acquire() is None
            try:
                note = run_loop.note_fields(path.read_text())
                assert note["environment"] == "(unset)"
                assert lock.driver["environment"] is None
            finally:
                lock.release()


def test_the_heartbeat_rewrites_the_note_while_the_lock_is_held():
    count = itertools.count()
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "run.lock"
        lock = run_loop.SliceLock(path, heartbeat_s=0.01)
        with patched(run_loop,
                     _heartbeat_stamp=lambda: f"beat-{next(count):04d}"):
            assert lock.acquire() is None
            try:
                first = run_loop.note_fields(path.read_text())
                assert first["heartbeat"] == "beat-0000"
                deadline = time.monotonic() + 5
                while True:
                    now = run_loop.note_fields(path.read_text())
                    if now.get("heartbeat", "") > "beat-0002":
                        break
                    assert time.monotonic() < deadline, "the note never beat"
                    time.sleep(0.01)
                assert run_loop.lock_held(path)
                assert lock._beat.is_alive()
                # the beat is the only field that moves
                del first["heartbeat"], now["heartbeat"]
                assert now == first
            finally:
                lock.release()


# A holder that dies without letting go: the kernel drops its flock with the
# process, and the note — beat and all — stays behind on the free lock.
DYING_HOLDER = """\
import os, sys
sys.path.insert(0, sys.argv[1])
import run_loop
lock = run_loop.SliceLock(run_loop.Path(sys.argv[2]), heartbeat_s=0.01)
assert lock.acquire() is None
os._exit(0)
"""


def test_release_stops_the_heartbeat_before_it_cuts_the_note():
    """A clean release leaves an empty note for good — no beat lands after
    it — so the next holder finds no previous note; a holder that died
    holding the lock still leaves its note for the next one to find."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "run.lock"
        lock = run_loop.SliceLock(path, heartbeat_s=0.01)
        assert lock.acquire() is None
        beat = lock._beat
        time.sleep(0.05)
        lock.release()
        assert not beat.is_alive()
        time.sleep(0.05)   # where a beat that outlived the release would land
        assert path.read_text() == ""
        assert not run_loop.lock_held(path)
        again = run_loop.SliceLock(path)
        assert again.acquire() is None
        assert again.previous_note == ""
        again.release()

        subprocess.run([sys.executable, "-c", DYING_HOLDER,
                        str(Path(run_loop.__file__).parent), str(path)],
                       check=True, timeout=30)
        assert not run_loop.lock_held(path)
        assert again.acquire() is None
        try:
            left = run_loop.note_fields(again.previous_note)
            assert left["pid"] != str(os.getpid()) and "heartbeat" in left
        finally:
            again.release()


def test_the_run_records_its_driver_and_a_resume_replaces_it():
    """state.json says where the run is: the driver run.lock's note names,
    on disk before the start is reported — and a resume's, once a resume
    holds the lock, wherever the run was before."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        seen = []
        first = ScriptedLoop(
            slice_dir, [("code-writer", {"outcome": "blocked",
                                         "summary": "x"})], repo_root=repo)
        first.on_start = lambda: seen.append(load_state(slice_dir)["driver"])
        with environment_id("env-a"), \
                contextlib.redirect_stderr(io.StringIO()):
            assert run_to_exit(first) == 3
        driver = load_state(slice_dir)["driver"]
        assert seen == [driver]
        assert driver == {"environment": "env-a",
                          "host": run_loop.socket.gethostname(),
                          "pid": os.getpid(), "started": driver["started"]}

        r = ScriptedLoop(slice_dir, [V["exec_done"], V["review_signoff"],
                                     *TAIL], resume=True, repo_root=repo)
        r.on_start = lambda: seen.append(load_state(slice_dir)["driver"])
        with environment_id("env-b"):
            assert run_to_exit(r) == 0
        resumed = load_state(slice_dir)["driver"]
        assert resumed["environment"] == "env-b"
        assert resumed["started"] != driver["started"]
        assert seen[1] == resumed


def status_lines(slice_dir):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        run_loop.cmd_status(type("Args", (), {"slice_dir": str(slice_dir)})())
    return out.getvalue().splitlines()


def test_status_names_the_driver_and_whether_it_runs():
    record = {"environment": "env-a", "host": "pod-a", "pid": 4242,
              "started": "2026-10-12T03:00:00+02:00"}
    named = ("driver: env env-a  host pod-a  pid 4242  "
             "started 2026-10-12T03:00:00+02:00")
    state = {"slice": "075_waited", "run_phase": "phases", "driver": record}
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = run_record(tmp, state=state)
        assert status_lines(slice_dir)[1] == f"  {named} — not running"
        note = ("environment: env-a\nhost: pod-a\npid: 4242\nstarted: s\n"
                "heartbeat: 2026-10-12T03:05:00+02:00\n")
        with holding(slice_dir, note=note):
            assert status_lines(slice_dir)[1] == (
                f"  {named} — running, heartbeat 2026-10-12T03:05:00+02:00")
        # a holder the record does not name is named from its note
        with holding(slice_dir, note="host: pod-b\npid: 7\n"):
            assert status_lines(slice_dir)[1] == (
                f"  {named} — run.lock is held by env ?  host pod-b  pid 7, "
                "heartbeat (none)")
        # the live lock of this process, as a driver takes it
        lock = run_loop.SliceLock(slice_dir / "run.lock")
        with environment_id("env-c"), \
                patched(run_loop, _heartbeat_stamp=lambda: "beat-1"):
            assert lock.acquire() is None
        try:
            state["driver"] = lock.driver
            (slice_dir / "state.json").write_text(json.dumps(state))
            line = status_lines(slice_dir)[1]
            assert line.startswith("  driver: env env-c  host ")
            assert line.endswith("— running, heartbeat beat-1")
        finally:
            lock.release()
        # a state.json from before the record
        del state["driver"]
        (slice_dir / "state.json").write_text(json.dumps(state))
        assert status_lines(slice_dir)[1] == \
            "  driver: (not recorded) — not running"


def test_the_reattach_prompt_says_the_stop_is_not_an_outcome():
    text = run_loop.REATTACH_PROMPT.format(verdict_path="/v.json")
    assert "is not an outcome of your work" in text
    assert "never report `blocked`" in text
    assert text.rstrip().endswith("write your verdict to /v.json.")


# `wait` and `stop` against a hand-built run record.

def run_record(tmp, state=None, log="", note=None, bail=None):
    slice_dir = Path(tmp) / "slices" / "075_waited"
    slice_dir.mkdir(parents=True)
    if state is not None:
        (slice_dir / "state.json").write_text(json.dumps(state))
    if log is not None:
        (slice_dir / "log.txt").write_text(log)
    if note is not None:
        (slice_dir / "run.lock").write_text(note)
    if bail is not None:
        (slice_dir / "bailout.json").write_text(json.dumps(bail))
    return slice_dir


@contextlib.contextmanager
def holding(slice_dir, note=None):
    """The run.lock held as a live driver holds it — on an open file
    description of its own, so the probe `wait` and `stop` make fails."""
    fd = os.open(slice_dir / "run.lock", os.O_RDWR | os.O_CREAT, 0o644)
    fcntl.flock(fd, fcntl.LOCK_EX)
    if note is not None:
        os.ftruncate(fd, 0)
        os.write(fd, note.encode())
    try:
        yield
    finally:
        os.close(fd)


def call(cmd, **args):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            cmd(type("Args", (), args)())
        except SystemExit as e:
            return e.code, out.getvalue(), err.getvalue()
    raise AssertionError(f"{cmd.__name__} did not exit")


def wait(slice_dir, for_seconds=0, from_offset=None):
    return call(run_loop.cmd_wait, slice_dir=str(slice_dir),
                for_seconds=for_seconds, from_offset=from_offset)


RUNNING_STATE = {
    "run_phase": "phases",
    "phases": {"2": {"stage": "review"}},
    "in_flight": {"phase": "2", "role": "code-reviewer", "round": 2,
                  "started_at": "2026-10-01T03:00:00+00:00"},
}


def test_wait_answers_2_when_there_is_no_run_to_wait_on():
    with tempfile.TemporaryDirectory() as tmp:
        code, _, err = wait(Path(tmp) / "nope")
        assert code == 2 and "not found" in err
        slice_dir = run_record(tmp)
        code, _, err = wait(slice_dir)
        assert code == 2 and "never started" in err


def test_wait_answers_0_with_the_exit_and_the_bail():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = run_record(
            tmp, state={"run_phase": "test", "exit": {"code": 4, "ts": "t"}},
            bail={"reason": "operator_question", "phase": "3",
                  "question": True, "details": "which auth?\nline two"},
            log="[10:00:00] [P3] [code-writer] → question: which auth?\n")
        code, out, _ = wait(slice_dir, from_offset=0)
        assert code == 0
        lines = out.splitlines()
        assert lines[0] == "ended: exit 4"
        assert "reason: operator_question (P3)" in lines
        assert "question: True" in lines
        assert "details: which auth?" in lines and "  line two" in lines
        assert "[10:00:00] [P3] [code-writer] → question: which auth?" in lines
        assert not any(line.startswith("next:") for line in lines)
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = run_record(
            tmp, state={"run_phase": "done", "exit": {"code": 0, "ts": "t"}})
        code, out, _ = wait(slice_dir)
        assert (code, out) == (0, "ended: exit 0\n")


def test_wait_answers_5_with_the_status_and_the_next_wait():
    log = ("[03:00:00] [P2] [code-reviewer] session starting\n"
           "    [P2] [code-reviewer] [1s] [text] Reading the diff.\n"
           "    [P2] [code-reviewer] [9s] [tool] Bash git diff\n"
           "    [P2] [code-reviewer] [20s] [text] Now the tests.\n"
           "    [P2] [code-reviewer] [30s] [tool] Read x.py\n")
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = run_record(tmp, state=RUNNING_STATE, log=log)
        size = (slice_dir / "log.txt").stat().st_size
        with holding(slice_dir):
            code, out, _ = wait(slice_dir)
        assert code == run_loop.WAIT_RUNNING == 5
        lines = out.splitlines()
        assert re.fullmatch(
            r"running: phases · P2 review r2 · code-reviewer in flight "
            r"\S+ \(cap 1h00m\) · last log line \d+s ago", lines[0]), lines[0]
        assert lines[1] == "latest from code-reviewer: Now the tests."
        assert lines[-1] == (f"next: python3 {run_loop.SCRIPT} wait "
                             f"{os.path.abspath(slice_dir)} --from {size}")
        assert len(lines) == 3


def test_wait_answers_6_for_a_driver_gone_without_an_exit_record():
    note = "host: pod\npid: 4242\nstarted: 2026-10-01T03:00:00+00:00\n"
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = run_record(tmp, state=RUNNING_STATE, note=note,
                               log="[03:00:00] [P2] start\n")
        code, out, _ = wait(slice_dir, from_offset=0)
        assert code == run_loop.WAIT_KILLED == 6
        lines = out.splitlines()
        assert lines[0] == "killed: the driver is gone and left no exit record"
        assert lines[1:4] == ["  host: pod", "  pid: 4242",
                              "  started: 2026-10-01T03:00:00+00:00"]
        assert "[03:00:00] [P2] start" in lines
        # nothing in flight is narrated for a dead driver
        assert not any(line.startswith("latest from") for line in lines)
        assert lines[-1] == (f"next: python3 {run_loop.SCRIPT} run "
                             f"{os.path.abspath(slice_dir)} --resume --detach")


def test_wait_returns_when_the_driver_lets_the_lock_go():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = run_record(tmp, state=RUNNING_STATE)
        fd = os.open(slice_dir / "run.lock", os.O_RDWR | os.O_CREAT, 0o644)
        fcntl.flock(fd, fcntl.LOCK_EX)

        def finish():
            state = dict(RUNNING_STATE, exit={"code": 0, "ts": "t"})
            (slice_dir / "state.json").write_text(json.dumps(state))
            os.close(fd)

        timer = threading.Timer(0.2, finish)
        timer.start()
        try:
            with patched(run_loop, WAIT_POLL=0.02):
                code, out, _ = wait(slice_dir, for_seconds=30)
        finally:
            timer.join()
        assert code == 0 and out.startswith("ended: exit 0")


def test_wait_shows_the_drivers_own_lines_since_the_offset():
    driver = [f"[10:00:{i:02d}] [P1] line {i}" for i in range(45)]
    lines = []
    for i, line in enumerate(driver):
        lines.append(line)
        lines.append(f"    [P1] [code-writer] [{i}s] [tool] Bash ls")
    lines.insert(3, "[10:00:01] [P1] [code-writer] session "
                    "0f0e-11 — transcript /home/x/.claude/0f0e-11.jsonl")
    lines.insert(5, "")
    lines.append("[10:01:00] " + "y" * 300)
    text = "\n".join(lines) + "\n" + "[10:02:00] half a li"
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "log.txt"
        data = text.encode()     # offsets are bytes, and "—" is three
        path.write_bytes(data)
        out, read_to = run_loop.log_digest(path, 0)
        # complete lines only: the offset stops at the last newline
        assert read_to == data.rindex(b"\n") + 1
        assert out[0] == "(6 earlier lines omitted)"
        assert len(out) == 41
        assert out[1:-1] == driver[6:]
        assert len(out[-1]) == 200 and out[-1].endswith("…")
        assert not any("transcript" in line or line.startswith(" ")
                       for line in out)
        # from an offset: only what came after it
        offset = data.index(driver[44].encode())
        assert run_loop.log_digest(path, offset)[0] == \
            [driver[44], out[-1]]
        # an offset past the end is a rewritten log: start over
        assert run_loop.log_digest(path, len(data) + 100)[1] == read_to
        # the partial line is the next check's, once it is whole
        with open(path, "ab") as f:
            f.write(b"ne\n")
        assert run_loop.log_digest(path, read_to)[0] == \
            ["[10:02:00] half a line"]
        assert run_loop.log_digest(Path(tmp) / "absent.txt", 7) == ([], 0)
        # bytes that are not UTF-8 are read, not fatal
        path.write_bytes(b"[10:00:00] caf\xe9\n")
        assert run_loop.log_digest(path, 0)[0] == ["[10:00:00] caf�"]


def test_wait_reads_from_its_own_start_by_default():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = run_record(tmp, state={"exit": {"code": 0, "ts": "t"}},
                               log="[10:00:00] old line\n")
        code, out, _ = wait(slice_dir)
        assert out == "ended: exit 0\n"
        code, out, _ = wait(slice_dir, from_offset=0)
        assert "[10:00:00] old line" in out.splitlines()


def test_the_narration_is_the_in_flight_sessions_own():
    log = ("[03:00:00] [P1] [code-writer] session starting\n"
           "    [P1] [code-writer] [1s] [text] The writer's words.\n"
           "[03:10:00] [P1] [code-reviewer] session starting\n"
           "    [P1] [code-reviewer] [1s] [tool] Bash git diff\n")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "log.txt"
        path.write_text(log)
        assert run_loop.latest_narration(path, len(log)) is None
        path.write_text(log + "    [P1] [code-reviewer] [5s] [text] Mine.\n")
        assert run_loop.latest_narration(path, path.stat().st_size) == "Mine."


def stop(slice_dir):
    return call(run_loop.cmd_stop, slice_dir=str(slice_dir))


def test_stop_on_a_free_lock_says_nothing_runs():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = run_record(tmp, state={}, note="host: h\npid: 1\n")
        code, out, _ = stop(slice_dir)
        assert code == 1 and "no driver is running" in out


def test_stop_refuses_a_driver_on_another_host():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = run_record(tmp, state={})
        with holding(slice_dir, note="host: elsewhere\npid: 1\n"):
            code, _, err = stop(slice_dir)
        assert code == 2 and "runs on host elsewhere" in err
        with holding(slice_dir,
                     note="environment: env-b\nhost: elsewhere\npid: 1\n"):
            code, _, err = stop(slice_dir)
        assert code == 2
        assert "runs on host elsewhere (environment env-b)" in err


# A driver in miniature: holds run.lock with the real note's shape, and on
# SIGINT records its exit and lets the lock go, as RunLoop.run does. With
# `ignore` it starts the way a background job may — SIGINT ignored, which is
# why the detached driver resets it.
DRIVER_CHILD = """\
import fcntl, json, os, signal, socket, sys, time
slice_dir, mode = sys.argv[1], sys.argv[2]
signal.signal(signal.SIGINT, signal.SIG_IGN if mode == "ignore"
              else signal.default_int_handler)
fd = os.open(os.path.join(slice_dir, "run.lock"), os.O_RDWR | os.O_CREAT)
fcntl.flock(fd, fcntl.LOCK_EX)
os.write(fd, f"host: {socket.gethostname()}\\npid: {os.getpid()}\\n".encode())
print("ready", flush=True)
try:
    while True:
        time.sleep(0.02)
except KeyboardInterrupt:
    with open(os.path.join(slice_dir, "state.json"), "w") as f:
        json.dump({"exit": {"code": 130, "ts": "t"}}, f)
    os.ftruncate(fd, 0)
    sys.exit(130)
"""


def driver_child(slice_dir, mode="default"):
    child = subprocess.Popen(
        [sys.executable, "-c", DRIVER_CHILD, str(slice_dir), mode],
        stdout=subprocess.PIPE, text=True)
    assert child.stdout.readline() == "ready\n"
    return child


def test_stop_interrupts_the_driver_and_waits_for_the_lock():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = run_record(tmp, state={})
        child = driver_child(slice_dir)
        try:
            with patched(run_loop, STOP_POLL=0.02):
                code, out, _ = stop(slice_dir)
            assert child.wait(timeout=10) == 130
        finally:
            child.kill()
            child.wait()
        assert code == 0, out
        assert f"sent SIGINT to the driver (pid {child.pid})" in out
        assert out.splitlines()[-1] == "stopped: exit 130"
        assert not run_loop.lock_held(slice_dir / "run.lock")


def test_stop_gives_up_on_a_driver_that_keeps_the_lock():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = run_record(tmp, state={})
        child = driver_child(slice_dir, "ignore")
        try:
            with patched(run_loop, STOP_POLL=0.02, STOP_WAIT=0.2):
                code, out, _ = stop(slice_dir)
            assert child.poll() is None
        finally:
            child.kill()
            child.wait()
        assert code == 1 and "still holds run.lock" in out


# The handshake, around bodies that stand in for the run.

def await_file(path, seconds=5.0):
    deadline = time.monotonic() + seconds
    while not path.exists():
        assert time.monotonic() < deadline, f"{path} never appeared"
        time.sleep(0.01)
    time.sleep(0.05)   # written whole: the child renames it into place
    return path.read_text()


def test_detach_relays_a_refusal_with_its_code():
    def refuse(started):
        print("Error: state.json exists. Pass --resume", file=sys.stderr)
        sys.exit(2)

    with tempfile.TemporaryDirectory() as tmp:
        log = Path(tmp) / "log.txt"
        assert run_loop.detach(refuse, log) == (
            None, 2, "Error: state.json exists. Pass --resume\n")
        assert not log.exists()


def test_detach_relays_a_crash_and_a_death_before_the_start():
    def crash(started):
        raise ValueError("boom")

    def die(started):
        os._exit(9)

    with tempfile.TemporaryDirectory() as tmp:
        log = Path(tmp) / "log.txt"
        pid, code, text = run_loop.detach(crash, log)
        assert (pid, code) == (None, 1) and "ValueError: boom" in text
        pid, code, text = run_loop.detach(die, log)
        assert (pid, code) == (None, 1) and "died before it started" in text


def test_detach_returns_the_started_drivers_pid_and_leaves_it_running():
    """The driver runs on in a session of its own with SIGINT live — even
    where it was launched with SIGINT ignored — and after the start its
    stderr is log.txt."""
    def body(started):
        print("before the start", file=sys.stderr)
        started()
        print("after the start", file=sys.stderr)
        print("stdout goes nowhere")
        facts = {"pid": os.getpid(), "sid": os.getsid(0),
                 "sigint": signal.getsignal(signal.SIGINT)
                 is signal.default_int_handler}
        tmp_path = done.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(facts))
        os.replace(tmp_path, done)
        raise RuntimeError("a traceback after the start")

    with tempfile.TemporaryDirectory() as tmp:
        log = Path(tmp) / "log.txt"
        log.write_text("earlier run\n")
        done = Path(tmp) / "facts.json"
        saved = signal.signal(signal.SIGINT, signal.SIG_IGN)
        try:
            pid, code, text = run_loop.detach(body, log)
        finally:
            signal.signal(signal.SIGINT, saved)
        assert code == 0 and text == "before the start\n"
        facts = json.loads(await_file(done))
        assert facts["pid"] == pid != os.getpid()
        assert facts["sid"] != os.getsid(0)
        assert facts["sigint"] is True
        deadline = time.monotonic() + 5
        while "RuntimeError" not in log.read_text():
            assert time.monotonic() < deadline, log.read_text()
            time.sleep(0.01)
        written = log.read_text()
        assert written.startswith("earlier run\nafter the start\n")
        assert "stdout goes nowhere" not in written


def test_run_detach_prints_the_pid_and_the_wait_to_follow():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = Path(tmp) / "074_x"
        slice_dir.mkdir()
        (slice_dir / "log.txt").write_text("12345\n")
        loop = type("Loop", (), {"log_path": slice_dir / "log.txt"})()
        out = io.StringIO()
        with patched(run_loop, detach=lambda body, log: (4242, 0, "")), \
                contextlib.redirect_stdout(out):
            run_loop.run_detached(loop, slice_dir)
        lines = out.getvalue().splitlines()
        assert "pid 4242" in lines[0]
        assert lines[-1] == (f"next: python3 {run_loop.SCRIPT} wait "
                             f"{os.path.abspath(slice_dir)} --from 6")
        err = io.StringIO()
        with patched(run_loop, detach=lambda body, log: (None, 2, "Error: x\n")), \
                contextlib.redirect_stderr(err):
            try:
                run_loop.run_detached(loop, slice_dir)
            except SystemExit as e:
                assert e.code == 2
            else:
                raise AssertionError("a refusal did not exit")
        assert err.getvalue() == "Error: x\n"


def test_detach_with_a_dry_run_is_a_usage_error():
    with tempfile.TemporaryDirectory() as tmp:
        code, _, err = call(run_loop.cmd_run, slice_dir=tmp, resume=False,
                            verbose=False, dry_run=True, detach=True)
        assert code == 2 and "--detach" in err


def test_a_detached_run_refuses_and_runs_through_the_real_handshake():
    """The run itself under `detach`: a resume-less second start comes back
    as the parent's exit 2, and a run that starts is waited on to its exit
    record."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, repo = make_slice(tmp)
        r = ScriptedLoop(slice_dir, [V["exec_done"], V["review_signoff"],
                                     *TAIL], repo_root=repo)

        def body(started):
            r.on_start = started
            r.run()

        pid, code, text = run_loop.detach(body, r.log_path)
        assert code == 0 and pid, text
        with patched(run_loop, WAIT_POLL=0.02):
            code, out, _ = wait(slice_dir, for_seconds=30, from_offset=0)
        assert code == 0, out
        assert out.splitlines()[0] == "ended: exit 0"
        assert any("merged" in line for line in out.splitlines())

        again = ScriptedLoop(slice_dir, [], repo_root=repo)

        def body2(started):
            again.on_start = started
            again.run()

        pid, code, text = run_loop.detach(body2, again.log_path)
        assert (pid, code) == (None, 2) and "Pass --resume" in text
        assert exit_record(slice_dir)["code"] == 0


# -- Pilot's halt: the halt file, the safe points, exit 7 --------------------
#
# Pilot writes its halt file while a usage halt or the project's pause holds
# (docs/pilot.md § The nudge and the halt). The run stops at its next safe
# point — nothing in flight — with state.json current, exits 7, and the
# resume carries on from where it stood once the file is gone.

@contextlib.contextmanager
def halt_file(tmp):
    """The halt file's path for this test, pointed at by the module — absent
    until the test (or a script step's effect) touches it."""
    path = Path(tmp) / "quota-limit-halt-requested"
    with patched(run_loop, HALT_FILE=path):
        yield path


def raises_the_halt(path):
    """A script step's effect: Pilot's halt begins while the session works."""
    def effect(loop):
        path.touch()
    return effect


def test_a_halt_at_the_start_runs_nothing_and_records_nothing():
    with tempfile.TemporaryDirectory() as tmp, halt_file(tmp) as halt:
        slice_dir, repo = make_slice(tmp)
        halt.touch()
        r = ScriptedLoop(slice_dir, [], repo_root=repo)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            assert run_to_exit(r) == 7
        assert not r.spawned
        assert not (slice_dir / "state.json").exists(), (
            "a refused start leaves no record: the next start is not a "
            "--resume")
        assert f"Halted: {halt} is present" in err.getvalue()

        # A resume refused the same way leaves the record as it stood.
        state = {"slice": "074_test_slice", "exit": {"code": 7, "ts": "t"},
                 "halts": [{"at": "before P2", "run_phase": "phases",
                            "ts": "t"}]}
        (slice_dir / "state.json").write_text(json.dumps(state))
        r = ScriptedLoop(slice_dir, [], resume=True, repo_root=repo)
        with contextlib.redirect_stderr(io.StringIO()):
            assert run_to_exit(r) == 7
        assert load_state(slice_dir) == state


def test_a_halt_between_phases_stops_before_the_next_and_the_resume_goes_on():
    with tempfile.TemporaryDirectory() as tmp, halt_file(tmp) as halt:
        slice_dir, repo = make_slice(tmp, phases=[("1", "First"),
                                                  ("2", "Second")])
        script = [V["exec_done"], (*V["review_signoff"],
                                   raises_the_halt(halt))]
        r = ScriptedLoop(slice_dir, script, repo_root=repo)
        with contextlib.redirect_stderr(io.StringIO()):
            assert run_to_exit(r) == 7
        assert [(role, pid) for role, pid, *_ in r.spawned] == [
            ("code-writer", "1"), ("code-reviewer", "1")]
        state = load_state(slice_dir)
        assert state["exit"]["code"] == 7
        assert state["run_phase"] == "phases"
        [stop] = state["halts"]
        assert (stop["at"], stop["run_phase"]) == ("before P2", "phases")
        assert state["phases"]["1"]["status"] == "merged"
        assert "2" not in state["phases"]
        assert not state.get("bailouts")
        assert not (slice_dir / "bailout.json").exists()
        assert f"HALTED before P2: {halt} is present" in \
            (slice_dir / "log.txt").read_text()

        halt.unlink()
        r2 = ScriptedLoop(slice_dir, [V["exec_done"], V["review_signoff"],
                                      *TAIL], resume=True, repo_root=repo)
        assert run_to_exit(r2) == 0
        assert r2.spawned[0][:3] == ("code-writer", "2", 1)
        assert load_state(slice_dir)["halts"] == [stop]


def test_a_halt_before_the_consult_draws_no_consult_number():
    """A consult never reattaches, so the halt comes before its number: a
    number drawn and never answered would be a consult_<n>.json nothing
    wrote."""
    with tempfile.TemporaryDirectory() as tmp, halt_file(tmp) as halt:
        slice_dir, repo = make_slice(tmp)
        script = [V["exec_done"], (*V["review_signoff"],
                                   raises_the_halt(halt))]
        r = ScriptedLoop(slice_dir, script, repo_root=repo)
        with contextlib.redirect_stderr(io.StringIO()):
            assert run_to_exit(r) == 7
        state = load_state(slice_dir)
        assert state["halts"][-1]["at"].startswith("before the consult (")
        assert state.get("consult_seq", 0) == 0

        halt.unlink()
        r2 = ScriptedLoop(slice_dir, list(TAIL), resume=True, repo_root=repo)
        assert run_to_exit(r2) == 0
        assert load_state(slice_dir)["consult_seq"] == 1


def test_a_halt_before_a_session_banks_its_round_for_the_resume():
    """The round's number is drawn and the in-flight record written before
    the halt point, as before an interrupt at the same place: the resume
    dispatches it fresh, under the same number, with nothing counted twice."""
    with tempfile.TemporaryDirectory() as tmp, halt_file(tmp) as halt:
        slice_dir, repo = make_slice(tmp)
        script = [("code-writer", {"outcome": "done", "summary": "built"},
                   raises_the_halt(halt))]
        r = SpawningLoop(slice_dir, script, repo_root=repo)
        with patched(run_loop, run_kc_session=r.run_kc_session), \
                contextlib.redirect_stderr(io.StringIO()):
            assert run_to_exit(r) == 7
        state = load_state(slice_dir)
        flight = state["in_flight"]
        assert (flight["role"], flight["phase"], flight["round"],
                flight["session"]) == ("code-reviewer", "1", 1, None)
        assert state["halts"][-1]["at"] == \
            "before the [P1] [code-reviewer] session"
        assert "code-reviewer" not in [h["role"] for h in state["history"]]
        assert "[P1] [code-reviewer] session starting" not in \
            (slice_dir / "log.txt").read_text()

        halt.unlink()
        script = [("code-reviewer", {"outcome": "signoff", "summary": "ok"}),
                  ("consult", {"outcome": "complete", "summary": "done"}),
                  ("test-agent", {"outcome": "clean", "summary": "ok"}),
                  ("doc-writer", {"outcome": "done", "summary": "ok"})]
        r2 = SpawningLoop(slice_dir, script, resume=True, repo_root=repo)
        # the repo as the halted run left it: the writer's commit on P1
        r2.fake_git = r2.git = r.fake_git
        r2.git_ok, r2.git_raw = r.fake_git.ok, r.fake_git.raw
        with patched(run_loop, run_kc_session=r2.run_kc_session):
            assert run_to_exit(r2) == 0
        assert r2.session_resumes[0][:2] == ("code-reviewer", None), (
            "dispatched fresh: there was no session to reattach")
        state = load_state(slice_dir)
        assert state["phases"]["1"]["review_rounds"] == 1
        assert state["phases"]["1"]["executor_rounds"] == 1


def test_a_halt_ends_the_session_limit_sleep_and_stops_before_the_redispatch():
    with tempfile.TemporaryDirectory() as tmp, halt_file(tmp) as halt:
        slice_dir, repo = make_slice(tmp)
        r = SpawningLoop(slice_dir, [("code-writer", SESSION_LIMIT_TEXT)],
                         repo_root=repo)

        def sleep(seconds):
            r.sleeps.append(seconds)
            halt.touch()   # Pilot's halt begins during the wait

        r._sleep = sleep
        with patched(run_loop, run_kc_session=r.run_kc_session), \
                contextlib.redirect_stderr(io.StringIO()):
            assert run_to_exit(r) == 7
        assert r.sleeps == [run_loop.HALT_POLL], (
            "the file is looked for before every step of the sleep")
        state = load_state(slice_dir)
        assert state["in_flight"]["round"] == 1
        assert state["phases"]["1"]["executor_rounds"] == 1
        assert state["halts"][-1]["at"] == \
            "before the [P1] [code-writer] session"
        log = (slice_dir / "log.txt").read_text()
        assert "halt requested — the session-limit sleep ends early" in log


def test_a_halt_in_the_devlock_wait_lets_go_with_nothing_held():
    with tempfile.TemporaryDirectory() as tmp:
        lease = Path(tmp) / "devlock.lease"
        holder = Path(tmp) / "dev-holder"
        holder.write_text("session: someone else\n")
        fd = os.open(lease, os.O_RDWR | os.O_CREAT, 0o644)
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            lock = run_loop.DevLock(lease)
            polls = []

            def halt():
                polls.append(1)
                return len(polls) >= 2

            try:
                lock.acquire("test phase", lambda m: None,
                             lambda s: None, halt=halt)
            except run_loop.Halted as e:
                assert e.where == "waiting for the devlock (test phase)"
            else:
                raise AssertionError("the wait did not end in Halted")
            assert len(polls) == 2
            assert not lock.held
            assert holder.read_text() == "session: someone else\n", (
                "the other holder's note is not this lock's to remove")
        finally:
            os.close(fd)


def test_a_halt_before_a_push_leaves_it_for_the_resume():
    with tempfile.TemporaryDirectory() as tmp, halt_file(tmp) as halt:
        slice_dir, repo = make_slice(tmp, config=rc(test=False))
        script = [V["exec_done"], V["review_signoff"],
                  (*V["consult_complete"], raises_the_halt(halt))]
        r = ScriptedLoop(slice_dir, script, repo_root=repo)
        with contextlib.redirect_stderr(io.StringIO()):
            assert run_to_exit(r) == 7
        assert pushes(r) == []
        assert load_state(slice_dir)["halts"][-1]["at"] == \
            f"before pushing main in {repo}"

        halt.unlink()
        r2 = ScriptedLoop(slice_dir, [V["doc_done"]], resume=True,
                          repo_root=repo)
        assert run_to_exit(r2) == 0
        assert (str(repo), "main") in pushes(r2)


def test_a_halt_passes_the_wrap_ups_leave_out_and_the_resume_starts_it_over():
    """Halted is a BaseException, as an interrupt is: the wrap-up's
    leave-out, which catches every Exception, does not swallow it."""
    with tempfile.TemporaryDirectory() as tmp, halt_file(tmp) as halt:
        slice_dir, repo, sib = sibling_phase_slice(tmp)
        plant_waiting(slice_dir)
        script = wrap_script(repo, sib)
        role, verdict, model = script[-1]

        def hands_back(loop):
            model(loop)
            halt.touch()

        script[-1] = (role, verdict, hands_back)
        r = ScriptedLoop(slice_dir, script, repo_root=repo)
        with contextlib.redirect_stderr(io.StringIO()):
            assert run_to_exit(r) == 7
        assert not r.wrap_up_sessions
        state = load_state(slice_dir)
        assert state["doc_phase"]["stage"] == "wrap-up"
        assert state["wrap_up"]["outcome"] is None, "not left out"
        assert state["halts"][-1]["at"] == "before the [wrap-up] session"

        halt.unlink()
        r2 = ScriptedLoop(slice_dir, [], resume=True, repo_root=repo,
                          wrap_ups=[(WRAP_DONE, wrap_up_fixes(repo, sib))])
        for name in ("refs", "parents", "branch_at", "dirty_roots",
                     "spec_head", "specs_committed", "spec_snapshots"):
            setattr(r2.fake_git, name, getattr(r.fake_git, name))
        assert run_to_exit(r2) == 0
        assert len(r2.wrap_up_sessions) == 1
        assert load_state(slice_dir)["wrap_up"]["outcome"] == "landed"


def test_wait_answers_0_with_the_halt_and_where_it_stopped():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = run_record(
            tmp, state={"run_phase": "phases", "exit": {"code": 7, "ts": "t"},
                        "halts": [{"at": "before P1", "run_phase": "phases",
                                   "ts": "t"},
                                  {"at": "before P3", "run_phase": "phases",
                                   "ts": "t"}]})
        code, out, _ = wait(slice_dir)
        assert code == 0
        assert out.splitlines() == [
            "ended: exit 7",
            f"halted before P3: {run_loop.HALT_FILE} was present — once it "
            "is gone, resume with --resume --detach"]


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
