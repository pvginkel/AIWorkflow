"""turn_profile.py — replaying a transcript into per-turn facts.

Two kinds of fixture. The replay tests write a stream-json transcript into a
temp dir, exactly as Claude Code does (each assistant message logged several
times, tool results arriving in the next user message). The classification
tests build turn dicts directly — `_t(i, *calls)` — because what a class
depends on is the tool calls and their results, not how they were logged.

No agent is spawned, nothing is priced: `analyse` takes the pricing function,
and these tests hand it one that charges a flat rate per token — except the
one that checks a turn reaches slice_cost.py's long-prompt tier.
"""

import importlib.util
import json
import tempfile
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "turn_profile", Path(__file__).resolve().parent / "turn_profile.py"
)
tp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tp)
_sc_spec = importlib.util.spec_from_file_location(
    "slice_cost", Path(__file__).resolve().parent / "slice_cost.py"
)
slice_cost = importlib.util.module_from_spec(_sc_spec)
_sc_spec.loader.exec_module(slice_cost)

OPUS = "claude-opus-5"


def flat_cost(_model, tok, prompt_tokens=None):
    """A pricing function with one rate, so a cost is a token count / 1e6."""
    return sum(tok.values()) / 1_000_000


# -- transcript fixtures ----------------------------------------------------

def _assistant(mid, blocks=(), ts="2026-08-23T10:00:00Z", model=OPUS, **usage):
    u = {"input_tokens": 0, "output_tokens": 0, "cache_creation_input_tokens": 0,
         "cache_read_input_tokens": 0}
    u.update(usage)
    return {"type": "assistant", "timestamp": ts,
            "message": {"id": mid, "model": model, "content": list(blocks),
                        "usage": u}}


def _use(name, tid, **inp):
    return {"type": "tool_use", "id": tid, "name": name, "input": inp}


def _result(tid, text="", is_error=False):
    return {"type": "user", "timestamp": "2026-08-23T10:00:01Z",
            "message": {"content": [{"type": "tool_result", "tool_use_id": tid,
                                     "content": text, "is_error": is_error}]}}


def _text_user(text, **flags):
    return {"type": "user", "timestamp": "2026-08-23T10:00:01Z", **flags,
            "message": {"content": [{"type": "text", "text": text}]}}


def _str_user(text, **flags):
    return {"type": "user", "timestamp": "2026-08-23T10:00:01Z", **flags,
            "message": {"content": text}}


def _replay(records):
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "session.jsonl"
        path.write_text("\n".join(json.dumps(r) for r in records) + "\n")
        return tp.replay(path)


# -- turn fixtures for the classifier ---------------------------------------

def _call(name, key="", cmd="", res="", is_error=False):
    return {"name": name, "key": key or cmd[:160], "id": None, "cmd": cmd,
            "result_chars": len(res), "is_error": is_error, "res_head": res[:600]}


def _t(i, *calls, res_paths=(), **extra):
    return {"i": i, "tools": list(calls), "res_paths": set(res_paths), **extra}


def _classes(*turns, first_edit=None, **flags):
    return [r["cls"] for r in tp.classify_turns(list(turns), first_edit, **flags)]


def _cls(cmd, res="", is_error=False):
    """The class of a one-call turn running `cmd`, followed by a closing
    tool-less turn (so the call's turn is not the session's last)."""
    return _classes(_t(1, _call("Bash", cmd=cmd, res=res, is_error=is_error)), _t(2))[0]


# -- replay -----------------------------------------------------------------

def test_repeated_message_ids_are_one_turn_with_all_its_calls():
    """The stream logs an assistant message once per block; usage is counted
    once and the tool calls accumulate onto the same turn."""
    rep = _replay([
        _assistant("m1", [_use("Bash", "t1", command="cat a.py")],
                   input_tokens=10, cache_read_input_tokens=1_000),
        _assistant("m1", [_use("Bash", "t2", command="cat b.py")],
                   input_tokens=10, cache_read_input_tokens=1_000),
        _result("t1", "line\n"),
        _result("t2", "other\n"),
    ])
    (turn,) = rep["turns"]
    assert [c["cmd"] for c in turn["tools"]] == ["cat a.py", "cat b.py"]
    assert turn["ctx"] == 1_010          # input + cache_read + cache_write
    assert turn["result_chars"] == len("line\n") + len("other\n")


def test_results_attach_to_their_call_and_reveal_their_paths():
    rep = _replay([
        _assistant("m1", [_use("Grep", "t1", pattern="def run", path="tools")],
                   input_tokens=5),
        _result("t1", "tools/run_loop.py:120:def run()\n"),
    ])
    (turn,) = rep["turns"]
    assert turn["tools"][0]["is_error"] is False
    assert "tools/run_loop.py" in {str(p) for p in turn["res_paths"]}


def test_an_error_result_is_flagged_on_the_call():
    rep = _replay([
        _assistant("m1", [_use("Bash", "t1", command="close_out.py report.md list")]),
        _result("t1", "usage: close_out.py [-h] ...", is_error=True),
    ])
    assert rep["turns"][0]["tools"][0]["is_error"] is True


def test_injected_text_is_not_an_operator_prompt():
    rep = _replay([
        _assistant("m1", [], output_tokens=5),
        _text_user("<system-reminder>plan.md changed</system-reminder>"),
        _text_user("carry on"),
    ])
    assert rep["user_prompts"] == 1
    assert rep["injected_chars"] > 0


def test_a_message_without_usage_is_not_a_turn():
    rep = _replay([{"type": "assistant", "timestamp": "2026-08-23T10:00:00Z",
                    "message": {"id": "m1", "model": OPUS, "content": []}}])
    assert rep["turns"] == []


def test_a_record_ends_at_a_newline_only():
    """A U+2028/U+2029 inside a JSON string, or a lone carriage return between
    its tokens, does not cut the record: the turn on that line is replayed."""
    first = _assistant("m1", [{"type": "text", "text": "one two three"}],
                       output_tokens=5)
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "session.jsonl"
        path.write_text(json.dumps(first, ensure_ascii=False).replace(", ", ",\r", 1)
                        + "\n" + json.dumps(_assistant("m2", output_tokens=7)) + "\n",
                        newline="")
        rep = tp.replay(path)
    assert [t["out"] for t in rep["turns"]] == [5, 7]
    assert rep["turns"][0]["text_chars"] == len("one two three")


def test_a_streamed_message_counts_the_output_of_its_last_record():
    """A sub-agent transcript logs one message in several records whose
    output_tokens grow; the turn keeps the first record's input and cache
    tokens, the most output any record reports, and the last stop reason."""
    rep = _replay([
        _assistant("m1", [{"type": "text", "text": "a"}], input_tokens=10,
                   cache_read_input_tokens=1_000, output_tokens=21),
        {**_assistant("m1", [_use("Bash", "t1", command="cat a.py")], input_tokens=10,
                      cache_read_input_tokens=1_000, output_tokens=384,
                      output_tokens_details={"thinking_tokens": 200})},
        _result("t1", "x"),
    ])
    (turn,) = rep["turns"]
    assert turn["out"] == 384 and turn["think"] == 200
    assert turn["input"] == 10 and turn["cr"] == 1_000


def test_the_last_stop_reason_given_is_the_turns():
    first = _assistant("m1", [{"type": "text", "text": "a"}], output_tokens=5)
    last = _assistant("m1", [_use("Bash", "t1", command="ls")], output_tokens=9)
    last["message"]["stop_reason"] = "tool_use"
    (turn,) = _replay([first, last])["turns"]
    assert turn["stop"] == "tool_use"


def test_a_synthetic_message_is_no_turn():
    rep = _replay([
        _assistant("m1", [], cache_read_input_tokens=30_000),
        _assistant("m2", [], model="<synthetic>"),
        _assistant("m3", [], cache_read_input_tokens=30_000),
    ])
    assert [t["i"] for t in rep["turns"]] == [1, 2]
    assert tp.analyse(rep, flat_cost)["breaks"] == []


def test_only_the_operators_texts_are_prompts():
    """A task notification, a meta record, a local command and its output,
    an interruption and a compact summary are Claude Code's bookkeeping; a
    skill the operator invoked is one prompt."""
    rep = _replay([
        _assistant("m1", [], output_tokens=5),
        _str_user("<task-notification><task-id>b1</task-id></task-notification>"),
        _text_user("<task-notification>done</task-notification>"),
        _str_user("Base directory for this skill: …", isMeta=True),
        _str_user("<command-name>/clear</command-name>\n<command-message>clear"
                  "</command-message>\n<command-args></command-args>"),
        _str_user("<local-command-caveat>Caveat: …</local-command-caveat>", isMeta=True),
        _str_user("<local-command-stdout>Disconnected</local-command-stdout>"),
        _text_user("[Request interrupted by user]"),
        _str_user("This session is being continued …", isCompactSummary=True),
        _str_user("<command-message>run-slice</command-message>\n"
                  "<command-name>/run-slice</command-name>\n<command-args>047</command-args>"),
        _str_user("carry on"),
    ])
    assert rep["user_prompts"] == 2


def test_a_call_run_in_the_background_and_a_done_record_are_kept_on_the_call():
    (turn,) = _replay([
        _assistant("m1", [_use("Bash", "t1", command="kc project test",
                               run_in_background=True),
                          _use("Edit", "t2", file_path="/s/plan.md",
                               new_string="**Done (P3).** the gate landed")]),
    ])["turns"]
    assert [r["background"] for r in turn["tools"]] == [True, False]
    assert [r["done"] for r in turn["tools"]] == [False, True]


# -- what one Bash command did ----------------------------------------------

def test_a_command_splits_into_steps_but_not_inside_quotes_or_heredocs():
    assert tp.bash_segments("cat a.py; cat b.py && grep x c.py") == [
        "cat a.py", "cat b.py", "grep x c.py"]
    assert tp.bash_segments("close_out.py append --headline 'a; b'") == [
        "close_out.py append --headline 'a; b'"]
    assert len(tp.bash_segments(
        "python3 - <<'PY'\nimport os; os.remove('x')\nPY")) == 1


def test_reads_chained_in_one_command_are_counted_separately():
    """`tools/turn` cannot see this batching; `reads/turn` is the honest one."""
    turn = _t(1, _call("Bash", cmd="sed -n 1,40p plan.md && sed -n 1,20p slice.md"))
    _ops, _targets, reads = tp.turn_ops(turn)
    assert reads == 2
    assert tp.turn_ops(_t(1, _call("Read", key="plan.md")))[2] == 1


def test_an_edit_made_through_the_shell_is_an_edit():
    for cmd in ("sed -i 's/a/b/' run_loop.py",
                "echo hi > notes.md",
                "python3 - <<'PY'\nPath('x.py').write_text('a')\nPY"):
        assert "edit" in tp.bash_ops(cmd), cmd
    assert "edit" not in tp.bash_ops("kc project test 2>&1 | tail -5")


def test_a_gate_is_read_from_the_text_not_the_program():
    assert tp.bash_ops("cexec python sh -c 'uv run --with pytest pytest'") == ["gate"]
    assert tp.tool_class("Bash", "kc project test") == "gate"
    assert tp.tool_class("Bash", "git diff --stat") == "git-inspect"
    assert tp.tool_class("Read", "") == "Read"


CARD_PLAYWRIGHT = (
    'rm -rf test-results && timeout 1500 cexec modern-app pnpm playwright test '
    'tests/chat/chat-tab.spec.ts -g "closed again" --repeat-each=64 --workers=4 '
    '--reporter=line > /tmp/p9a-dbg3.log 2>&1; grep -c "^DBG" /tmp/p9a-dbg3.log; '
    'tail -3 /tmp/p9a-dbg3.log')
CARD_RUN_LOOP_GATE = ("git status --short; timeout 3500 python3 /x/dev/0.10.49/tools/"
                      "run_loop.py gate /s/phases/P9a/gate_spec.json 2>&1 | tail -30")


def test_a_node_gate_and_the_loops_gate_are_gates():
    """AIWF-156: the card's two commands, verbatim."""
    for cmd in (CARD_PLAYWRIGHT, CARD_RUN_LOOP_GATE):
        assert "gate" in tp.bash_ops(cmd), cmd
        assert _cls(cmd) == "gate"
        assert tp.tool_class("Bash", cmd) == "gate"
    for cmd in ("cd frontend && pnpm test", "pnpm -C frontend lint", "npm run build",
                "npx playwright test tests/x.spec.ts", "pnpm exec eslint src",
                "npx vitest run", "npx knip", "npx tsc --noEmit",
                "cexec modern-app sh -c 'cd frontend && pnpm lint'",
                "python3 /p/run_loop.py gate /s/gate_spec.json --detach",
                "python3 /p/run_loop.py gate /s/gate_spec.json --wait"):
        assert tp.bash_ops(cmd)[-1] == "gate", cmd


def test_a_check_is_a_gate_at_the_program_not_anywhere_in_the_text():
    for cmd in ("python3 /p/tools/spec_check.py /s", "python3 plugins/dev/tools/test_run_loop.py",
                "python -m unittest discover -s tests", "python3 -m pytest -q",
                "cexec go go vet ./...", "gofmt -l .", "shellcheck scripts/*.sh",
                "bash -n deploy.sh", "node --test out/test", "cexec iac helm lint chart",
                "terraform validate", "ansible-playbook site.yml --syntax-check"):
        assert tp.bash_ops(cmd) == ["gate"], cmd
    for cmd in ('grep -n "tmux\\|go test" Jenkinsfile', "cat test_run_loop.py",
                "echo 'run go vet next'", "grep -rn shellcheck docs"):
        assert "gate" not in tp.bash_ops(cmd), cmd


def test_the_rest_of_a_command_after_a_heredoc_is_still_read():
    cmd = "cat > notes.md <<'EOF'\nline\nEOF\nkc project test"
    assert tp.bash_ops(cmd) == ["edit", "gate"]
    assert tp._strip_heredocs(cmd).strip().endswith("kc project test")
    # two heredocs, and the shell between and after them
    cmd = ("cat > a.md <<'A'\nx\nA\npython3 /p/close_out.py append /s --headline y <<'B'\n"
           "z\nB\ngit status")
    assert tp.bash_ops(cmd) == ["edit", "record", "git-read"]


def test_a_variable_the_command_set_is_read_where_it_is_used():
    assert tp.bash_ops("T=/p/close_out.py; python3 $T append $R --headline x") == [
        "noop", "record"]
    assert tp.bash_ops('CO="python3 /p/close_out.py"; $CO list /s') == ["noop", "read"]
    assert tp.bash_ops("T=x") == ["noop"]


def test_what_a_substitution_ran_the_step_did():
    assert tp.bash_ops("H=$(git rev-parse HEAD)") == ["git-read"]
    assert tp.bash_ops('echo "$(kc project test)"') == ["gate", "noop"]
    assert tp.bash_ops("echo `git status --short`") == ["git-read", "noop"]
    assert tp.bash_ops("echo $((1 + 2))") == ["noop"]
    assert tp.bash_ops("echo '$(kc project test)' \\`pytest\\`") == ["noop"]
    assert tp.bash_ops('git commit -m "$(cat <<\'EOF\'\nfix: x\nEOF\n)"') == ["git-mutate"]


def test_a_step_splits_where_the_shell_does():
    assert tp.bash_segments('echo "a \\"b; c\\" d"; cat x.py') == [
        'echo "a \\"b; c\\" d"', "cat x.py"]
    assert tp.bash_segments("X=$(cd a; ls) && cat b.py") == ["X=$(cd a; ls)", "cat b.py"]
    assert tp.bash_segments("# what's next\nkc project lint") == ["kc project lint"]
    assert tp.bash_segments("pnpm dev & sleep 5") == ["pnpm dev", "sleep 5"]
    assert tp.bash_segments("kc project test > /tmp/t.log 2>&1") == [
        "kc project test > /tmp/t.log 2>&1"]


def test_a_wrapper_is_unwrapped_to_the_program_it_runs():
    for cmd, op in (("timeout -k 5 60 cexec python sh -c 'cd x && uv run pytest'", "gate"),
                    ("env -u VIRTUAL_ENV kc project lint", "gate"),
                    ("poetry run pytest -q", "gate"),
                    ("cexec python uv run --with ruff ruff check .", "gate"),
                    ("bash -lc \"git -C /w/x commit -m 'y'\"", "git-mutate"),
                    ("git -C /w/x --no-pager log -3", "git-read"),
                    ("git -c user.name=x commit -m y", "git-mutate")):
        assert tp.bash_ops(cmd)[-1] == op, cmd
    assert tp._seg_prog("timeout 30 cexec iac kubectl get pods") == "kubectl"
    assert tp._seg_prog("git -C /w/x --no-pager log") == "git log"


def test_a_shell_function_does_what_its_body_does():
    assert tp.bash_ops("t() { kc project test; }\nt")[-1] == "gate"


def test_a_shell_builtin_does_nothing():
    for cmd in ("continue", "break", "return 1", "exit 0", "local x", "shift", "trap x EXIT",
                ":", ". ./env.sh", "eval $x"):
        assert tp.bash_ops(cmd) == ["noop"], cmd


def test_a_read_program_is_a_read_whatever_its_arguments_say():
    assert tp.bash_ops('grep -n "tmux\\|go test" Jenkinsfile') == ["read"]
    assert tp.bash_ops("which track_build.py") == ["noop"]
    assert tp.bash_ops("git merge-base HEAD main") == ["git-read"]
    assert tp.bash_ops("git stash list") == ["git-read"]
    assert tp.bash_ops('python3 /p/close_out.py rule /s/close-out.md B1 '
                       '--did "fixed (gated: kc project lint)"') == ["record"]
    assert tp.bash_ops("sleep 30") == ["wait"]


def test_the_read_and_git_tables():
    for cmd in ("awk '{print $1}' a.txt", "sort a.txt", "uniq -c", "cut -d: -f1 a",
                "md5sum a", "sha256sum a", "cmp a b", "file a", "readlink -f a", "od -c a",
                "yq .a f.yaml", "ps aux", "pgrep -f x", "env", "id", "openssl x509 -in c"):
        assert tp.bash_ops(cmd) == ["read"], cmd
    for cmd in ("git grep -n x", "git ls-tree HEAD", "git rev-list -1 HEAD", "git cat-file -p x",
                "git reflog -3", "git check-ignore -v a", "git ls-remote origin",
                "git describe --tags", "git config user.name", "git config --get a.b",
                "git fetch -q origin", "git worktree list", "git branch -a"):
        assert tp.bash_ops(cmd) == ["git-read"], cmd
    for cmd in ("git pull --ff-only", "git mv a b", "git rm -q a", "git clone u d",
                "git worktree add /w/s HEAD", "git worktree remove /w/s", "git branch -D x",
                "git stash", "git stash pop", "git push origin main"):
        assert tp.bash_ops(cmd) == ["git-mutate"], cmd
    for cmd in ("git checkout HEAD -- a.py", "git checkout -- a.py", "git restore a.py"):
        assert tp.bash_ops(cmd) == ["edit"], cmd
    assert tp.bash_ops("git restore --staged a.py") == ["git-mutate"]
    assert tp.bash_ops("git config user.name 'X Y'") == ["other"]


def test_an_external_probe_is_a_read():
    for cmd in ("cexec iac kubectl -n x get pods", "kubectl --context prd describe pod p",
                "kubectl logs deploy/x", "kubectl top pods", "kubectl auth can-i get x",
                "kubectl config view", "curl -s http://x/y", "wget -qO- http://x",
                "gh api repos/o/r/contents/a", "gh pr view 3", "gh run list",
                "gh issue list", "helm template x chart", "helm get values x",
                "bao kv get secret/x", "vault kv metadata get secret/x",
                "docker inspect img", "crane ls reg/x", "skopeo inspect docker://x",
                "terraform show", "terraform output -json"):
        assert tp.bash_ops(cmd) == ["read"], cmd
    for cmd in ("kubectl delete pod x", "kubectl -n x exec p -- ls", "curl -X POST http://x",
                "curl -s -d @f http://x", "curl -F f=@a http://x", "gh api -X PATCH repos/o/r",
                "gh pr create", "helm upgrade x chart", "bao kv put secret/x a=b",
                "terraform apply"):
        assert tp.bash_ops(cmd) == ["other"], cmd
    assert tp.bash_ops("gh run watch 12") == ["wait"]


def test_the_workflows_own_scripts_go_by_their_verb():
    co = "python3 /p/dev/0.10.49/tools/close_out.py"
    for verb in ("list", "show", "worklist", "labels", "counts", "render"):
        assert tp.bash_ops(f"{co} {verb} /s/close-out.md") == ["read"], verb
    for verb in ("append", "note", "strike", "init", "stamp", "rule", "settle", "propose"):
        assert tp.bash_ops(f"{co} {verb} /s/close-out.md B1") == ["record"], verb
    assert tp.bash_ops(f"{co} append --help") == ["read"]
    assert tp.bash_ops("python3 /p/asks.py list /s") == ["read"]
    assert tp.bash_ops("python3 /p/asks.py append /s --title x") == ["record"]
    rl = "python3 /p/run_loop.py"
    assert tp.bash_ops(f"{rl} wait /s --for 240") == ["wait"]
    assert tp.bash_ops(f"{rl} status /s") == ["read"]
    assert tp.bash_ops(f"{rl} run /s --dry-run") == ["read"]
    assert tp.bash_ops(f"{rl} run /s --detach") == ["dispatch"]
    assert tp.bash_ops(f"{rl} run /s") == ["wait"]
    assert tp.bash_ops("python3 /p/plan_loop.py wait /s") == ["wait"]
    assert tp.bash_ops("python3 /p/long_run.py wait /tmp/lr --for 240") == ["wait"]
    assert tp.bash_ops("python3 /p/long_run.py start --dir /tmp/lr -- kc project test") == [
        "gate"]
    for script in ("preflight.py --for run", "slice_cards.py /s", "checks.py /s",
                   "slice_cost.py /s"):
        assert tp.bash_ops(f"python3 /p/{script}") == ["read"], script
    assert tp.bash_ops("python3 /p/slice_cost.py /s --write-state") == ["record"]
    assert tp.bash_ops("python3 /p/close_slice.py /s") == ["git-mutate"]
    assert tp.bash_ops("/p/allocate-next-slice.sh --number 041") == ["record"]
    assert tp.bash_ops("kc session create-headless --prompt x") == ["dispatch"]
    assert tp.bash_ops("kc session send abc 'go on'") == ["dispatch"]
    for cmd in ("kc session list", "kc session status x", "kc catalog", "kc project info",
                "kc env describe"):
        assert tp.bash_ops(cmd) == ["read"], cmd


def test_a_write_to_a_scratch_file_or_inside_quotes_is_no_edit():
    assert tp.bash_ops("jq '.a > 1' f.json") == ["read"]
    assert tp.bash_ops('python3 /p/close_out.py note /s B1 --text "X > Y"') == ["record"]
    assert tp.bash_ops("kc project test > /tmp/t.log 2>&1") == ["gate"]
    assert tp.bash_ops("cat > /tmp/x.json <<'EOF'\n{}\nEOF") == ["noop"]
    assert tp.bash_ops("echo hi > /dev/null; printf x > $TMPDIR/a") == ["noop", "noop"]
    assert tp.bash_ops("D=$(mktemp -d); echo x > $D/a.txt") == ["noop", "noop"]
    assert tp.bash_ops("grep x a.py | tee /tmp/hits") == ["read"]
    assert tp.bash_ops("python3 - <<'PY'\nPath('/tmp/x.json').write_text('a')\nPY") == [
        "other"]
    # a real file is an edit: a quoted target, a repo clone under /work/scratch
    assert tp.bash_ops('echo x > "notes.md"') == ["edit"]
    assert tp.bash_ops("echo x >> /work/scratch/Repo/a.py") == ["edit"]
    assert tp._bash_edit_targets("echo a > /tmp/x.md; echo b > notes.md") == ["notes.md"]
    turns = [_t(1, _call("Bash", cmd="kc project test > /tmp/t.log")),
             _t(2, _call("Bash", cmd="echo x > notes.md"))]
    assert tp.first_edit_turn(turns) == 2


def test_an_inline_script_that_only_reads_is_a_read():
    for cmd in ('python3 -c "import json; print(json.load(open(\'v.json\'))[\'items\'])"',
                "python3 - <<'PY'\nimport yaml\nprint(yaml.safe_load(open('a.yaml')))\nPY",
                "cat <<'PY' | python3 -\nfrom pathlib import Path\n"
                "print(Path('a').read_text())\nPY",
                "node -e \"console.log(require('fs').readFileSync('a.json', 'utf8'))\""):
        assert tp.bash_ops(cmd) == ["read"], cmd
    assert tp.bash_ops('python3 -c "print(1 + 1)"') == ["other"]
    assert tp.bash_ops("python3 - <<'PY'\np = open('a.py').read()\n"
                       "open('a.py', 'w').write(p)\nPY")[-1] == "edit"


# -- the turn classes -------------------------------------------------------

def test_work_beats_the_reads_that_led_to_it():
    """First match wins: a turn that read and then edited is an edit."""
    assert _classes(_t(1, _call("Bash", cmd="cat run_loop.py"),
                       _call("Edit", key="run_loop.py"))) == ["edit"]
    assert _classes(_t(1, _call("Bash", cmd="cat x.py && kc project test"))) == ["gate"]
    assert _classes(_t(1, _call("Bash", cmd="git add -A && git commit -m x"))) == ["commit"]


def test_writing_the_plan_or_a_verdict_is_a_record_not_an_edit():
    assert _classes(_t(1, _call("Edit", key="/s/170/plan.md"))) == ["record"]
    assert _classes(_t(1, _call("Write", key="/s/170/phases/P1/result.json"))) == ["record"]
    # a turn that writes both is the edit it also was
    assert _classes(_t(1, _call("Edit", key="/s/170/plan.md"),
                       _call("Edit", key="run_loop.py"))) == ["edit"]


def test_orientation_ends_at_the_first_edit():
    turns = [_t(1, _call("Bash", cmd="cat plan.md")),
             _t(2, _call("Edit", key="run_loop.py")),
             _t(3, _call("Bash", cmd="cat run_loop.py"))]
    assert _classes(*turns, first_edit=2) == ["orient-read", "edit", "work-read"]
    # no edit at all: everything the session read was orientation
    assert _classes(turns[0], turns[2]) == ["orient-read", "orient-read"]


def test_a_failed_call_is_a_fumble_and_repeating_it_is_a_retry():
    """The loop's commands end in `2>&1`, so failure is read from the text."""
    bad = _call("Bash", cmd="close_out.py /s/170/close-out.md list",
                res="usage: close_out.py [-h] slice_dir ...")
    help_ = _call("Bash", cmd="close_out.py --help", res="usage: close_out.py [-h]")
    ok = _call("Bash", cmd="close_out.py /s/170 list", res="B1 ...")
    # reading a tool's help first is a read: its `usage:` is the answer
    assert _classes(_t(1, help_), _t(2)) == ["orient-read", "record"]
    # re-running the same tool within two turns of its failure is the retry —
    # reading its help after failing counts there too, not as a second fumble
    assert _classes(_t(1, bad), _t(2, help_), _t(3, ok)) == ["fumble", "retry", "retry"]
    assert tp.classify_turns([_t(1, bad)], None)[0]["fumble_key"] == "close_out.py"


def test_the_quiet_classes():
    assert _classes(_t(1), _t(2)) == ["think", "record"]
    assert _cls("sleep 30") == "wait"
    assert _cls("git diff --stat") == "git-inspect"
    assert _classes(_t(1, _call("Agent", key="Explore: find callers"))) == ["dispatch"]
    assert _cls("curl -s localhost:8080/health") == "orient-read"
    assert _cls("cexec python uv run tools/pilot.py items list") == "other"


def test_a_failed_read_does_not_make_a_read_of_another_file_a_retry():
    bad = _call("Bash", cmd="sed -n 1,40p src/a.ts", res="usage: sed [-n] script [file]",
                is_error=True)
    other = _call("Bash", cmd="sed -n 1,40p src/b.ts", res="export const b = 1")
    again = _call("Bash", cmd="sed -n 1,20p src/a.ts", res="export const a = 1")
    assert _classes(_t(1, bad), _t(2, other), _t(3)) == ["fumble", "orient-read", "record"]
    assert _classes(_t(1, bad), _t(2, again), _t(3)) == ["fumble", "retry", "record"]
    # two cexec calls run two different programs
    bad = _call("Bash", cmd="cexec python uv run tools/pilot.py x",
                res="error: invalid choice: 'x'")
    go = _call("Bash", cmd="cexec go go build ./...", res="")
    assert _classes(_t(1, bad), _t(2, go), _t(3))[1] == "other"


def test_a_search_that_found_nothing_is_no_failure():
    for cmd in ("grep -rn foo src", "kc project test 2>&1 | grep -c FAIL", "git diff --quiet",
                "diff a b", "[ -f x ]", "ls missing"):
        assert not tp._failed(_call("Bash", cmd=cmd, res="Exit code 1", is_error=True)), cmd
    # but not when the program said why
    assert tp._failed(_call("Bash", cmd="python3 x.py | grep y", is_error=True,
                            res="Exit code 2\ngrep: invalid option -- 'y'\nusage: grep"))


def test_a_loop_wait_reporting_its_exit_code_is_no_failure():
    for cmd in ("python3 /p/run_loop.py wait /s; echo $?", "python3 /p/plan_loop.py wait /s",
                "python3 /p/long_run.py wait /tmp/lr --for 240",
                "python3 /p/run_loop.py gate /s/spec.json --wait",
                "timeout 3000 track_build.py App --hash abc"):
        for code in (4, 5, 6, 7):
            rec = _call("Bash", cmd=cmd, res=f"Exit code {code}\nended", is_error=True)
            assert not tp._failed(rec), (cmd, code)
    assert tp._failed(_call("Bash", cmd="python3 /p/run_loop.py wait /s", is_error=True,
                            res="Exit code 3\nerror: no state"))


def test_a_probe_answered_no_such_file_did_not_fail():
    """A call that only reads ignores its error flag and `No such file`: the
    answer to a probe, not a misused tool — as is a read program's own
    `No such file` inside a call that does more."""
    for cmd, res in (("cat /s/result.json", "cat: /s/result.json: No such file or directory"),
                     ("ls /s/P1", "ls: cannot access '/s/P1': No such file or directory"),
                     ("git show HEAD:a.py", "fatal: path 'a.py' does not exist")):
        rec = _call("Bash", cmd=cmd, res=f"Exit code 2\n{res}", is_error=True)
        assert not tp._failed(rec), cmd
        assert _classes(_t(1, rec), _t(2))[0] in ("orient-read", "git-inspect")
    assert not tp._failed(_call(
        "Bash", cmd="ls /s/state.json; python3 /p/run_loop.py run /s --detach",
        res="ls: cannot access '/s/state.json': No such file or directory\ndetached"))
    assert tp._failed(_call("Bash", cmd="python3 x.py", res=(
        "python3: can't open file '/w/x.py': [Errno 2] No such file or directory")))
    # a probe that misused its program still fumbled
    assert tp._failed(_call("Bash", cmd="sed -n --foo a", res="usage: sed [-n] ..."))


def test_a_failure_marker_counts_on_a_diagnostic_line_only():
    grep_hit = "src/run.py:120:    raise SystemExit('command not found')"
    assert not tp._failed(_call("Bash", cmd="grep -n 'not found' src/run.py", res=grep_hit))
    assert not tp._failed(_call("Bash", cmd="python3 /p/close_out.py show /s B1",
                                res="B1 — the gate says No such file or directory"))
    for res in ("/bin/bash: line 1: foo: command not found",
                "cexec: error: unrecognized arguments: --bar",
                "PermissionError: [Errno 13] Permission denied: 'x'",
                "Traceback (most recent call last):\n  File ..."):
        assert tp._failed(_call("Bash", cmd="foo --bar", res=res)), res


def test_an_operators_refusal_is_what_the_call_attempted():
    no = "The user doesn't want to proceed with this tool use. The tool use was rejected."
    assert not tp._failed(_call("Bash", cmd="sed -i 's/a/b/' x.py", res=no, is_error=True))
    assert _cls("sed -i 's/a/b/' x.py", res=no, is_error=True) == "edit"
    assert _classes(_t(1, _call("Edit", key="x.py", res=no, is_error=True)), _t(2))[0] == "edit"


def test_a_tool_other_than_bash_goes_by_its_name():
    def one(name):
        return _classes(_t(1, _call(name)), _t(2))[0]
    assert one("ToolSearch") == "orient-read" and one("Skill") == "orient-read"
    assert one("ListAgents") == "orient-read"
    assert one("SendMessage") == "dispatch"
    assert one("mcp__kubecoder-fleet__start_headless_session") == "dispatch"
    assert one("mcp__kubecoder-fleet__send_session_message") == "dispatch"
    for name in ("Monitor", "ScheduleWakeup", "TaskOutput", "BashOutput"):
        assert one(name) == "wait", name
    for name in ("TodoWrite", "TaskCreate", "TaskUpdate", "TaskList", "TaskGet"):
        assert one(name) == "think", name
    for name in ("mcp__youtrack__update_issue", "mcp__fieldnotes__post",
                 "mcp__pilot__register_document", "mcp__kubecoder-worker__notification",
                 "mcp__trello__add_card_to_list"):
        assert one(name) == "record", name
    for name in ("mcp__jenkins__getBuildLog", "mcp__youtrack__search_issues",
                 "mcp__gitblit__read_file", "mcp__jenkins__whoAmI"):
        assert one(name) == "orient-read", name
    assert one("mcp__kubecoder-worker__queue_resume_nudge") == "other"
    assert one("AskUserQuestion") == "other"
    # a noop tool beside work is the work
    assert _classes(_t(1, _call("TodoWrite"), _call("Read", key="a.py")), _t(2))[0] == (
        "orient-read")


def test_the_workflows_records_are_records():
    for path in ("/s/phases/P1/code_review_r1.md", "/s/phases/P2/plan_review_r3.json",
                 "/s/verification.json", "/s/asks/2-the-plan.json", "/s/asks/2-the-plan.md",
                 "/s/close-out.json", "/s/close-out.md", "/s/phases/P1/result_r2.json"):
        assert _classes(_t(1, _call("Write", key=path)), _t(2))[0] == "record", path
    assert _cls("cat > /s/phases/P1/code_review_r1.md <<'EOF'\n# r1\nEOF") == "record"


def test_a_turn_that_writes_a_record_and_code_is_an_edit():
    """Whatever wrote the record — a close-out entry beside an Edit is still
    the edit it also was."""
    assert _classes(_t(1, _call("Bash", cmd="python3 /p/close_out.py append /s --headline x"),
                       _call("Edit", key="run_loop.py")), _t(2))[0] == "edit"
    assert _classes(_t(1, _call("Write", key="/s/phases/P1/result.json"),
                       _call("Bash", cmd="python3 - <<'PY'\nopen('x', 'w').write('a')\nPY")),
                    _t(2))[0] == "edit"


def test_a_turn_without_a_tool_call():
    """The session's last is its hand-back; one that waits on work left
    running in the background is a wait; any other is thinking."""
    assert _classes(_t(1, _call("Read", key="a.py")), _t(2), _t(3)) == [
        "orient-read", "think", "record"]
    bg = _call("Bash", cmd="kc project test", is_error=False)
    bg["background"] = True
    assert _classes(_t(1, bg), _t(2), _t(3)) == ["gate", "wait", "record"]
    agent = _call("Agent", key="general-purpose: x",
                  res="Async agent launched successfully. agentId: a1")
    assert _classes(_t(1, agent), _t(2), _t(3)) == ["dispatch", "wait", "record"]
    detach = _call("Bash", cmd="python3 /p/run_loop.py run /s --detach")
    assert _classes(_t(1, detach), _t(2), _t(3)) == ["dispatch", "wait", "record"]
    assert _classes(_t(1, _call("Read", key="a.py")), _t(2, notified=True), _t(3)) == [
        "orient-read", "wait", "record"]


def test_a_notification_after_a_tool_less_turn_makes_it_a_wait():
    rep = _replay([
        _assistant("m1", [_use("Bash", "t1", command="kc project test",
                               run_in_background=True)]),
        _result("t1", "Command running in background with ID: b1"),
        _assistant("m2", [{"type": "text", "text": "waiting"}]),
        _str_user("<task-notification><task-id>b1</task-id></task-notification>"),
        _assistant("m3", [_use("Bash", "t3", command="cat /tmp/out")]),
        _result("t3", "ok"),
        _assistant("m4", [{"type": "text", "text": "anything else?"}]),
        _str_user("yes, go on"),
        _assistant("m5", [{"type": "text", "text": "done"}]),
    ])
    assert [t["notified"] for t in rep["turns"]] == [False, True, False, False, False]
    classes = [r["cls"] for r in tp.analyse(rep, flat_cost)["classes"]]
    assert classes == ["gate", "wait", "orient-read", "think", "record"]


def test_a_reviewers_reads_are_its_work():
    """reads_are_work: no orientation — every read turn, a git-inspect one
    too, is a work-read, and the orientation figures are 0."""
    rep = _replay(_session_records())
    a = tp.analyse(rep, flat_cost, reads_are_work=True)
    classes = [r["cls"] for r in a["classes"]]
    assert classes[:3] == ["work-read"] * 3
    m = a["metrics"]
    assert m["first_edit_turn"] == 1 and m["orient_turns_edit"] == 0
    assert m["orient_turns"] == 0 and m["orient_cost"] == 0 and m["orient_cost_share"] == 0
    assert _classes(_t(1, _call("Bash", cmd="git diff a..b")), _t(2),
                    first_edit=1, reads_are_work=True)[0] == "work-read"
    assert tp.first_edit_turn([_t(5, _call("Read", key="a")), _t(6)], reads_are_work=True) == 5
    # off by default: the same session orients
    assert [r["cls"] for r in tp.analyse(rep, flat_cost)["classes"]][:3] == ["orient-read"] * 3


def test_a_plan_authors_plan_is_its_work():
    """plan_is_edit: a write to plan.md is an edit — unless it wrote a
    done-record — and it ends orientation."""
    plan = _call("Edit", key="/s/plan.md")
    done = {**_call("Edit", key="/s/plan.md"), "done": True}
    turns = [_t(1, _call("Read", key="/s/slice.md")), _t(2, plan), _t(3, done), _t(4)]
    assert _classes(*turns, first_edit=2, plan_is_edit=True) == [
        "orient-read", "edit", "record", "record"]
    assert tp.first_edit_turn(turns, plan_is_edit=True) == 2
    assert tp.first_edit_turn(turns) is None
    assert _classes(*turns) == ["orient-read", "record", "record", "record"]
    sed = _call("Bash", cmd="sed -i 's/a/b/' /s/plan.md")
    assert _classes(_t(1, sed), _t(2), plan_is_edit=True)[0] == "edit"
    assert _classes(_t(1, _call("Write", key="/s/verification.json")), _t(2),
                    plan_is_edit=True)[0] == "record"


# -- batching ---------------------------------------------------------------

def test_a_run_of_read_turns_folds_into_its_first_turn():
    out = tp.classify_turns(
        [_t(1, _call("Bash", cmd="cat a.py")),
         _t(2, _call("Bash", cmd="cat b.py")),
         _t(3, _call("Bash", cmd="cat c.py")),
         _t(4, _call("Edit", key="a.py"))], 4)
    assert [r.get("batchable", False) for r in out] == [False, True, True, False]


def test_strict_batching_keeps_only_the_reads_that_did_not_need_the_last_one():
    """Turn 2 reads a file turn 1's result named — it could not have been
    batched with it. Turn 3 re-reads what was already in context."""
    out = tp.classify_turns(
        [_t(1, _call("Bash", cmd="cat a.py"), res_paths=["b.py"]),
         _t(2, _call("Bash", cmd="cat b.py")),
         _t(3, _call("Bash", cmd="cat a.py")),
         _t(4, _call("Edit", key="a.py"))], 4)
    assert [r.get("batchable", False) for r in out] == [False, True, True, False]
    assert [r.get("batchable_strict", False) for r in out] == [False, False, True, False]


def test_a_search_is_never_strictly_batchable():
    """A grep's target is a pattern, not a path already in context."""
    out = tp.classify_turns(
        [_t(1, _call("Read", key="a.py")),
         _t(2, _call("Grep", key="run in .")),
         _t(3, _call("Edit", key="a.py"))], 3)
    assert out[1]["batchable"] is True and out[1]["batchable_strict"] is False


# -- analyse ----------------------------------------------------------------

def _session_records():
    """Nine turns: three orientation reads, an edit, a gate, a fumble, its
    retry, a commit and the hand-back."""
    ctx = {"cache_read_input_tokens": 30_000}
    return [
        _assistant("m1", [_use("Bash", "t1", command="cat plan.md")],
                   input_tokens=1_000, output_tokens=100),
        _result("t1", "# plan"),
        _assistant("m2", [_use("Bash", "t2", command="cat run_loop.py")],
                   output_tokens=100, **ctx),
        _result("t2", "code"),
        _assistant("m3", [_use("Bash", "t3", command="cat plan.md")],
                   output_tokens=100, **ctx),
        _result("t3", "# plan"),
        _assistant("m4", [_use("Edit", "t4", file_path="run_loop.py")],
                   output_tokens=100, **ctx),
        _result("t4", "ok"),
        _assistant("m5", [_use("Bash", "t5", command="kc project test")],
                   output_tokens=100, **ctx),
        _result("t5", "OK"),
        _assistant("m6", [_use("Bash", "t6", command="close_out.py rep.md list")],
                   output_tokens=100, **ctx),
        _result("t6", "usage: close_out.py [-h] slice_dir"),
        _assistant("m7", [_use("Bash", "t7", command="close_out.py /s/170 list")],
                   output_tokens=100, **ctx),
        _result("t7", "B1"),
        _assistant("m8", [_use("Bash", "t8", command="git commit -am x")],
                   output_tokens=100, **ctx),
        _result("t8", "1 file changed"),
        _assistant("m9", [], output_tokens=100, **ctx),
    ]


def test_analyse_reports_what_the_session_did():
    m = tp.analyse(_replay(_session_records()), flat_cost)["metrics"]
    assert m["turns"] == 9
    assert m["turn_class_turns"] == {
        "orient-read": 3, "edit": 1, "gate": 1, "fumble": 1, "retry": 1,
        "commit": 1, "record": 1}          # the closing tool-less turn: a hand-back
    assert m["first_edit_turn"] == 4 and m["orient_turns_edit"] == 3
    # 8 calls over 9 turns; 5 read ops — the three `cat`s and both
    # `close_out.py list`, which reads the report
    assert m["tools_per_turn"] == 0.89 and m["reads_per_turn"] == 0.56
    assert m["avoidable_turns"] == 3          # fumble + retry + one strict batch
    assert m["retry_turns"] == 1 and m["fumble_turns"] == 1
    assert m["batchable_turns"] == 2 and m["batchable_strict_turns"] == 1


def test_analyse_prices_every_turn_with_the_function_it_is_given():
    a = tp.analyse(_replay(_session_records()), flat_cost)
    m = a["metrics"]
    tokens = sum(m["tok"][k] for k in ("input", "cache_read", "cache_write", "output"))
    assert m["cost"] == round(tokens / 1_000_000, 4)
    assert abs(sum(a["turn_cost"]) - m["cost"]) < 1e-9
    assert abs(sum(m["turn_class_cost"].values()) - m["cost"]) < 1e-3
    assert m["ctx_first"] == 1_000 and m["ctx_max"] == 30_000


def test_a_prompt_that_did_not_come_back_from_cache_is_a_break():
    """Turn 2 was read from cache; turn 3's prompt was written again."""
    rep = _replay([
        _assistant("m1", cache_creation_input_tokens=30_000),
        _assistant("m2", cache_read_input_tokens=30_000,
                   cache_creation_input_tokens=500),
        _assistant("m3", ts="2026-08-23T10:20:00Z",
                   cache_creation_input_tokens=30_500),
    ])
    a = tp.analyse(rep, flat_cost)
    (brk,) = a["breaks"]
    assert brk["turn"] == 3 and brk["shortfall"] == 30_500
    assert brk["gap_s"] == 1_200                     # over the 5-minute TTL
    assert a["metrics"]["breaks"] == 1
    assert a["metrics"]["breaks_after_gap"] == 1
    assert a["metrics"]["gaps_over_ttl"] == 1
    assert brk["extra_cost"] == 0.0                  # flat_cost charges no tier


def test_a_long_prompt_turn_is_priced_at_the_long_tier():
    """Every price is handed the turn's prompt size: a Haiku 5.5 turn over
    100K of prompt bills at $0.50/$2.50, one under it at $0.10/$0.50."""
    t = {"model": "claude-haiku-5-5", "input": 1_000, "cr": 150_000, "cw": 0,
         "out": 1_000_000}
    c = tp.turn_tier_cost(t, slice_cost.cost_for)
    assert abs(c["output"] - 2.50) < 1e-9
    assert abs(c["input"] - 1_000 / 1e6 * 0.50) < 1e-9
    assert abs(c["cache_read"] - 150_000 / 1e6 * 0.50 * slice_cost.CACHE_READ_MULT) < 1e-9
    short = tp.turn_tier_cost({**t, "cr": 90_000}, slice_cost.cost_for)
    assert abs(short["output"] - 0.50) < 1e-9


def test_a_turns_cache_writes_are_priced_by_their_recorded_ttl():
    """The replay keeps the 1-hour part of a turn's cache writes, and the
    write tier prices it at 2× base input, the rest at 1.25×."""
    rep = _replay([_assistant(
        "m1", model="claude-opus-5-5", cache_creation_input_tokens=1_000_000,
        cache_creation={"ephemeral_5m_input_tokens": 400_000,
                        "ephemeral_1h_input_tokens": 600_000})])
    (t,) = rep["turns"]
    c = tp.turn_tier_cost(t, slice_cost.cost_for)
    assert abs(c["cache_write"] - (0.4 * 5.0 + 0.6 * 8.0)) < 1e-9
    no_breakdown = tp.turn_tier_cost({**t, "cw1h": 0}, slice_cost.cost_for)
    assert abs(no_breakdown["cache_write"] - 5.0) < 1e-9


def test_an_empty_transcript_analyses_to_nothing():
    assert tp.analyse({"turns": [], "user_prompts": 0, "injected_chars": 0},
                      flat_cost) == {}


if __name__ == "__main__":
    _tests = [v for k, v in sorted(globals().items())
              if k.startswith("test_") and callable(v)]
    for _fn in _tests:
        _fn()
        print(f"ok  {_fn.__name__}")
    print(f"\n{len(_tests)} passed")
