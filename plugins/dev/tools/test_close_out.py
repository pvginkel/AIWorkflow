"""Tests for close_out — the close-out report's store, routes and render.

A throwaway slice folder per test, under a `slices/` directory so `--for`
has slices to name; the contract and the template are read from the
plugin's own docs, so a doc edit the tool no longer agrees with fails here.
Stdlib only; runs standalone and under pytest.

Run: `python3 ${CLAUDE_PLUGIN_ROOT}/tools/test_close_out.py` or via pytest.
"""

import contextlib
import difflib
import hashlib
import importlib.util
import io
import json
import re
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "close_out", Path(__file__).resolve().parent / "close_out.py"
)
close_out = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(close_out)
ReportError = close_out.ReportError


def make_slice(tmp, name="007_argocd_tools_presync_hook", later=("012_later_slice",)):
    root = Path(tmp) / "specs" / "slices"
    slice_dir = root / name
    slice_dir.mkdir(parents=True)
    for other in later:
        (root / other).mkdir()
    (root / "backlog" / "031_in_the_backlog").mkdir(parents=True)
    (root / "completed" / "002_done_long_ago").mkdir(parents=True)
    return slice_dir


def report(slice_dir):
    return (slice_dir / "close-out.md").read_text()


def sha256(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def store(slice_dir):
    return json.loads((slice_dir / "close-out.json").read_text())


def entry_of(slice_dir, eid):
    return next(e for e in store(slice_dir)["entries"] if e["id"] == eid)


def run_cli(*argv, stdin=None):
    out, err = io.StringIO(), io.StringIO()
    old_stdin = sys.stdin
    if stdin is not None:
        sys.stdin = io.StringIO(stdin)
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = close_out.main([str(a) for a in argv])
            except SystemExit as e:      # argparse's own usage errors
                code = e.code
    finally:
        sys.stdin = old_stdin
    return code, out.getvalue(), err.getvalue()


# A defect with every label it carries, as the CLI takes them.
DEFECT = ["--kind", "defect", "--headline", "controller: the status line is wrong",
          "--body", "the body", "--consequence", "an operator reads a wrong status",
          "--provenance", "witnessed — code-reviewer, P3 r1",
          "--trigger", "ordinary-condition", "--impact", "broken", "--signal", "silent",
          "--fix", "design", "--area", "sensitive", "--repo", "KubeCoder"]
IMPROVEMENT = ["--kind", "improvement", "--headline", "drop the duplicate helper",
               "--body", "b", "--consequence", "none", "--provenance", "read — P2 r1",
               "--benefit", "code", "--felt", "not-observable", "--change", "remove",
               "--size", "one-edit", "--product-call", "no", "--prevents", "nothing",
               "--area", "plain", "--repo", "KubeCoder",
               "--proposal", "Drop it now: one caller, one edit."]


def with_flags(base, **flags):
    """`base` with each `--flag value` replaced (None drops the flag)."""
    out = list(base)
    for name, value in flags.items():
        flag = "--" + name.replace("_", "-")
        if flag in out:
            i = out.index(flag)
            del out[i:i + 2]
        if value is not None:
            out += [flag, value]
    return out


# An action and a decision: the defect's text, the three labels, a proposal.
ACTION = with_flags(DEFECT, kind="action", fix=None, area=None, repo=None,
                    proposal="Do it before the next run: one command.")
DECISION = with_flags(ACTION, kind="decision",
                      proposal="Keep it as it is; the other way costs a release.")


STATE = {
    "slice": "007_argocd_tools_presync_hook",
    "created_at": "2026-08-14T19:49:12+02:00",
    "updated_at": "2026-08-14T23:53:40+02:00",
    "run_phase": "done",
    "known_phases": ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11"],
    "appended_phases": ["9", "10", "11"],
    "bailouts": [{"reason": "protocol_failure", "phase": None, "question": False,
                  "ts": "t"},
                 {"reason": "blocked", "phase": "3", "question": False,
                  "ts": "t"}],
    "test_rounds": 1,
    "doc_phase": {"stage": "done"},
    "phases": {"1": {"landed": {"root": "/work/KubeCoder", "base": "a", "head": "b"}},
               "2": {"landed": {"root": "/work/KubeCoderSpecs", "base": "c", "head": "d"}}},
}


# -- routes: what should be fixed ---------------------------------------------

def E(kind, grade=None, labels=None, **kw):
    """An entry as the store holds one, for the route function."""
    return {"id": "X1", "kind": kind, "grade": grade, "labels": labels,
            "consequence": kw.get("consequence"), "strike": kw.get("strike"),
            "wrap_up": kw.get("wrap_up")}


def fix_labels(trigger="normal-use", impact="broken", signal="silent", fix="design",
               area="plain", repo="KubeCoder", **extra):
    labels = {"trigger": trigger, "impact": impact, "signal": signal, "fix": fix,
              "area": area, "repo": repo, **extra}
    return {k: v for k, v in labels.items() if v is not None}


def R(entry, touched=None):
    return close_out.route(entry, touched)[0]


def test_row_1_an_action_comes_to_the_operator_whatever_its_labels():
    assert R(E("action", labels=fix_labels(fix="one-edit", **{"for": "012"}))) \
        == "operator:action"
    assert close_out.route(E("action", labels=fix_labels()))[1] == "to you — an action"


def test_row_2_a_decision_comes_to_the_operator():
    assert R(E("decision", labels=fix_labels(trigger="none", impact="none",
                                             signal="none"))) == "operator:decision"
    assert close_out.route(E("decision", labels={}))[1] == "to you — a decision"


def test_row_3_an_event_that_describes_no_problem_is_the_record():
    none = {"trigger": "none", "impact": "none", "signal": "none"}
    assert close_out.route(E("event", labels=none)) == ("record", "the record")
    assert R(E("event", labels=fix_labels(trigger="none"))) == "record"
    assert R(E("event", labels=fix_labels(impact="none", signal="none"))) == "record"
    # An event that describes a problem goes down the table like a defect.
    assert R(E("event", labels=fix_labels(fix="one-edit"))) == "wrap-up:fix"


def test_row_4_input_for_a_later_slice_folds_before_row_6():
    lab = fix_labels(fix="one-edit", **{"for": "012"})
    assert close_out.route(E("defect", labels=lab)) == (
        "wrap-up:fold", "the wrap-up — fold into slice 012")
    # 4 before 5: the repo elsewhere does not matter to a fold.
    assert R(E("defect", labels=lab), touched={"Ansible"}) == "wrap-up:fold"


def test_row_5_a_fix_in_a_repo_the_slice_did_not_touch():
    touched = {"KubeCoder"}
    shows = fix_labels(repo="HelmCharts")
    assert close_out.route(E("defect", labels=shows), touched) == (
        "card:table", "card request — the fix lives in HelmCharts, which the slice did "
                      "not touch")
    quiet = fix_labels(trigger="fault", impact="degraded", repo="HelmCharts")
    assert close_out.route(E("defect", labels=quiet), touched) == (
        "closed:elsewhere", "closed — the fix lives in HelmCharts, which the slice did "
                            "not touch")
    # severe, or graded major, asks for the card where it would have closed
    assert R(E("defect", labels={**quiet, "impact": "severe"}), touched) == "card:table"
    assert R(E("defect", "major", labels=quiet), touched) == "card:table"
    # an unknown trigger counts as one that shows
    assert R(E("defect", labels={**quiet, "trigger": "unknown"}), touched) == "card:table"
    # loud on an ordinary condition does not show as row 8 says
    loud = fix_labels(trigger="ordinary-condition", signal="loud", repo="HelmCharts")
    assert R(E("defect", labels=loud), touched) == "closed:elsewhere"
    # 5 before 6: an easy fix elsewhere is still elsewhere
    assert R(E("defect", labels={**shows, "fix": "one-edit"}), touched) == "card:table"
    # the repo the slice touched, no repo label, or no run record: row 5 never fits
    assert R(E("defect", labels={**quiet, "repo": "KubeCoder"}), touched) == "closed:fault"
    no_repo = dict(quiet)
    del no_repo["repo"]
    assert R(E("defect", labels=no_repo), touched) == "closed:fault"
    assert R(E("defect", labels=quiet), None) == "closed:fault"


def test_row_6_prose_and_easy_fixes_go_to_the_wrap_up_to_fix():
    assert close_out.route(E("prose", labels=fix_labels(fix="design", area="sensitive",
                                                        trigger="fault"))) == (
        "wrap-up:fix", "the wrap-up — fix")
    for fix in ("one-edit", "several-places"):
        assert R(E("defect", labels=fix_labels(fix=fix))) == "wrap-up:fix"
        assert R(E("test-gap", labels=fix_labels(fix=fix, trigger="future-change"))) \
            == "wrap-up:fix"
    # a sensitive area is not an easy fix: it falls through to row 8
    assert R(E("defect", labels=fix_labels(fix="one-edit", area="sensitive"))) \
        == "wrap-up:fix-or-card"
    # 6 before 7: an easy fix is made even with an unknown impact
    assert R(E("defect", labels=fix_labels(fix="one-edit", impact="unknown"))) \
        == "wrap-up:fix"


def test_row_7_an_unknown_trigger_or_impact_goes_to_the_wrap_up_to_look():
    assert close_out.route(E("defect", labels=fix_labels(trigger="unknown"))) == (
        "wrap-up:look", "the wrap-up — look: its trigger is unknown")
    assert close_out.route(E("defect", labels=fix_labels(impact="unknown")))[1] == \
        "the wrap-up — look: its impact is unknown"
    assert close_out.route(E("defect", labels=fix_labels(trigger="unknown",
                                                         impact="unknown")))[1] == \
        "the wrap-up — look: its trigger and impact are unknown"
    # 7 before 8: normal use with an impact unknown is looked at, not fixed
    assert R(E("defect", labels=fix_labels(impact="unknown"))) == "wrap-up:look"


def test_row_8_by_trigger_and_signal():
    for trigger in ("normal-use", "ordinary-condition", "fault", "future-change"):
        for signal in ("loud", "silent", "unknown"):
            key = R(E("defect", labels=fix_labels(trigger=trigger, signal=signal,
                                                  impact="degraded")))
            eight = trigger == "normal-use" or (trigger == "ordinary-condition"
                                                and signal != "loud")
            assert (key == "wrap-up:fix-or-card") == eight, (trigger, signal, key)
    assert close_out.route(E("defect", labels=fix_labels()))[1] == \
        "the wrap-up — fix within its bar, or ask for a card"
    # no impact is not row 8, in normal use or not
    assert R(E("defect", labels=fix_labels(impact="none", signal="none"))) == \
        "closed:no-impact"


def test_row_9_severe_or_major_comes_to_the_operator_where_it_would_close():
    severe = fix_labels(trigger="fault", impact="severe")
    assert close_out.route(E("defect", labels=severe)) == (
        "operator:risk", "to you — a risk: severe, in place of a close")
    graded = fix_labels(trigger="future-change", impact="degraded")
    assert close_out.route(E("test-gap", "major", labels=graded)) == (
        "operator:risk", "to you — a risk: graded major, in place of a close")
    loud = fix_labels(trigger="ordinary-condition", signal="loud", impact="severe")
    assert R(E("defect", labels=loud)) == "operator:risk"
    # severe needs a trigger: nothing that could show is closed, severe or not
    assert R(E("defect", labels=fix_labels(trigger="none", impact="severe"))) == \
        "closed:no-impact"
    # 8 before 9: severe in normal use is the wrap-up's to fix or card
    assert R(E("defect", labels=fix_labels(impact="severe"))) == "wrap-up:fix-or-card"


def test_row_10_what_is_left_is_closed_on_its_ground():
    cases = {
        "closed:no-impact": (fix_labels(trigger="fault", impact="none", signal="none"),
                             "closed — it has no impact"),
        "closed:fault": (fix_labels(trigger="fault"), "closed — it needs a fault"),
        "closed:future-change": (fix_labels(trigger="future-change"),
                                 "closed — it cannot show with the code as it is"),
        "closed:loud": (fix_labels(trigger="ordinary-condition", signal="loud"),
                        "closed — it is loud on an ordinary condition"),
    }
    for key, (labels, words) in cases.items():
        assert close_out.route(E("defect", labels=labels)) == (key, words)
    # the ground is the first that fits: no impact before the fault
    assert R(E("defect", labels=fix_labels(trigger="none"))) == "closed:no-impact"


# -- routes: what could be better ---------------------------------------------

def imp_labels(benefit="code", felt="not-observable", change="adjust", size="one-edit",
               product_call="no", prevents="nothing", area="plain", repo="KubeCoder",
               **extra):
    return {"benefit": benefit, "felt": felt, "change": change, "size": size,
            "product-call": product_call, "prevents": prevents, "area": area,
            "repo": repo, **extra}


def test_improvement_row_1_input_for_a_later_slice_folds():
    lab = imp_labels(**{"for": "031"})
    assert close_out.route(E("improvement", labels=lab)) == (
        "wrap-up:fold", "the wrap-up — fold into slice 031")


def test_improvement_row_2_a_small_change_is_the_wrap_ups():
    for change in ("adjust", "remove"):
        for size in ("one-edit", "several-places"):
            assert close_out.route(E("improvement", labels=imp_labels(
                change=change, size=size))) == (
                "wrap-up:improvement", "the wrap-up — a small change, within its bar")
    # elsewhere: a card when it prevents something severe or is graded major
    touched = {"Ansible"}
    assert R(E("improvement", labels=imp_labels()), touched) == "closed:elsewhere"
    assert R(E("improvement", labels=imp_labels(prevents="severe")), touched) == \
        "card:table"
    assert R(E("improvement", "major", labels=imp_labels()), touched) == "card:table"
    # a product call, a design, or an addition is not a small change
    assert R(E("improvement", labels=imp_labels(product_call="yes"))) == \
        "operator:improvement"
    assert R(E("improvement", labels=imp_labels(size="design"))) == "operator:improvement"


def test_improvement_row_3_an_unfelt_addition_that_prevents_something_severe():
    for felt in ("after-change", "after-incident", "not-observable"):
        lab = imp_labels(change="add", size="design", felt=felt, prevents="severe")
        assert close_out.route(E("improvement", labels=lab)) == (
            "operator:risk", "to you — a risk: severe, in place of a close")
    lab = imp_labels(change="add", size="design", felt="after-change")
    assert close_out.route(E("improvement", "major", labels=lab))[1] == \
        "to you — a risk: graded major, in place of a close"


def test_improvement_row_4_an_unfelt_addition_is_closed():
    lab = imp_labels(change="add", size="design", felt="after-incident", prevents="broken")
    assert close_out.route(E("improvement", labels=lab)) == (
        "closed:unfelt",
        "closed — it adds something for a benefit that is not felt in use")


def test_improvement_row_5_the_rest_comes_to_the_operator():
    for lab in (imp_labels(change="add", felt="in-use"),
                imp_labels(change="add", felt="unknown"),      # unknown is not unfelt
                imp_labels(change="adjust", size="investigate"),
                imp_labels(change="unknown")):
        assert close_out.route(E("improvement", labels=lab)) == (
            "operator:improvement", "to you — an improvement")


def test_improvement_rows_in_order():
    # 1 before 2, 2 before 3: a small change that prevents something severe
    # is still the wrap-up's; 3 before 4 on severity alone.
    assert R(E("improvement", labels=imp_labels(**{"for": "012"}))) == "wrap-up:fold"
    assert R(E("improvement", labels=imp_labels(prevents="severe"))) == \
        "wrap-up:improvement"
    add = imp_labels(change="add", felt="after-change", size="one-edit")
    assert R(E("improvement", labels=add)) == "closed:unfelt"
    assert R(E("improvement", labels={**add, "prevents": "severe"})) == "operator:risk"


# The slices still to run as `slices_to_run` gives them: 012 unplanned, 051
# planned or running.
PENDING = {12: ("012", "unplanned"), 51: ("051", "planned")}
FOR_PLANNED = ("operator:action", "to you — an action: slice 051 is planned or running "
               "and its run never reads slice.md; add a phase or rule on its run")


def test_a_for_routes_by_the_stage_of_the_slice_it_names_in_both_tables():
    for kind, lab, without in (
            ("defect", fix_labels(fix="one-edit", area="plain"), "wrap-up:fix"),
            ("improvement", imp_labels(), "wrap-up:improvement")):
        def at(target, touched=None, lab=lab, kind=kind):
            return close_out.route(E(kind, labels={**lab, "for": target}), touched,
                                   PENDING)
        # still unplanned: the fold, as without the slices to look at
        assert at("012") == ("wrap-up:fold", "the wrap-up — fold into slice 012")
        assert at("12")[0] == at("012_later_slice")[0] == "wrap-up:fold"
        # planned or running: its run never reads slice.md — to the operator
        assert at("051") == FOR_PLANNED
        assert at("51")[0] == at("051_x")[0] == "operator:action"
        # no longer to run: the route the labels give without `for`
        assert at("002")[0] == without
        assert at("002") == close_out.route(E(kind, labels=lab), None, PENDING)
        # ...down to the rows below the fold: the repo elsewhere
        assert at("002", touched={"Ansible"})[0] in ("card:table", "closed:elsewhere")
        # without the slices to look at, every `for` folds
        assert R(E(kind, labels={**lab, "for": "051"})) == "wrap-up:fold"
        assert close_out.table_route(E(kind, labels={**lab, "for": "051"}), None,
                                     PENDING) == FOR_PLANNED


def test_unlabelled_struck_and_the_wrap_ups_marks():
    assert close_out.route(E("defect")) == ("unlabelled",
                                            "none yet — the entry has no labels")
    assert R(E("improvement")) == "unlabelled"
    # a kind the tool labels itself is never unlabelled
    assert R(E("event", consequence="none.")) == "record"
    assert R(E("event", consequence="the operator waits")) == "wrap-up:look"
    struck = {"reason": "dup", "by": None, "date": "2026-09-30", "commit": None}
    assert R(E("defect", labels=fix_labels(), strike=struck)) == "record"
    card = {"outcome": "card", "by": "wrap-up", "date": "2026-09-30", "text": ["x"]}
    left = {**card, "outcome": "left"}
    for labels in (fix_labels(), fix_labels(trigger="fault"),
                   fix_labels(trigger="fault", impact="severe")):
        assert close_out.route(E("defect", labels=labels, wrap_up=card)) == (
            "card:wrap-up", "card request — the wrap-up asks for a card")
    assert close_out.route(E("defect", labels=fix_labels(), wrap_up=left)) == (
        "closed:left", "closed — the wrap-up looked and left it")
    assert R(E("defect", labels=fix_labels(trigger="unknown"), wrap_up=left)) == \
        "closed:left"
    # left leaves every route that is not the wrap-up's as the table has it
    assert R(E("defect", labels=fix_labels(trigger="fault", impact="severe"),
               wrap_up=left)) == "operator:risk"
    assert R(E("defect", labels=fix_labels(trigger="fault"), wrap_up=left)) == \
        "closed:fault"
    assert R(E("action", labels={}, wrap_up=left)) == "operator:action"


def test_touched_repos_are_the_roots_of_the_state():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        assert close_out.touched_repos(slice_dir) is None
        (slice_dir / "state.json").write_text(json.dumps({"phases": {}}))
        assert close_out.touched_repos(slice_dir) is None
        (slice_dir / "state.json").write_text(json.dumps(STATE))
        assert close_out.touched_repos(slice_dir) == {"KubeCoder", "KubeCoderSpecs"}


def test_touched_repos_add_the_repos_the_plans_pending_phases_target():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        state = slice_dir / "state.json"
        # the plan's targets alone: no phase has landed yet
        state.write_text(json.dumps({"phases": {}, "target_roots": [
            "/work/KubeCoderSpecs", "/work/scratch/ElasticsearchDeploy"]}))
        assert close_out.touched_repos(slice_dir) == {
            "KubeCoderSpecs", "ElasticsearchDeploy"}
        # with the landed roots: the union
        state.write_text(json.dumps({**STATE, "target_roots": [
            "/work/KubeCoder", "/work/scratch/ElasticsearchDeploy"]}))
        assert close_out.touched_repos(slice_dir) == {
            "KubeCoder", "KubeCoderSpecs", "ElasticsearchDeploy"}
        # an empty list, or junk in it, adds nothing — and names no root alone
        state.write_text(json.dumps({**STATE, "target_roots": []}))
        assert close_out.touched_repos(slice_dir) == {"KubeCoder", "KubeCoderSpecs"}
        state.write_text(json.dumps({"phases": {}, "target_roots": ["", None, 3]}))
        assert close_out.touched_repos(slice_dir) is None
        state.write_text(json.dumps({"phases": {}, "target_roots": "/work/KubeCoder"}))
        assert close_out.touched_repos(slice_dir) is None


def test_a_repo_a_pending_phase_targets_is_not_elsewhere():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        # P1 landed in KubeCoder; P2, still in its rounds, targets a GitHub clone
        (slice_dir / "state.json").write_text(json.dumps({
            "phases": {"1": {"landed": {"root": "/work/KubeCoder"}},
                       "2": {"status": "in_progress"}},
            "target_roots": ["/work/scratch/ElasticsearchDeploy"]}))
        touched = close_out.touched_repos(slice_dir)
        shows = fix_labels(repo="ElasticsearchDeploy")
        quiet = fix_labels(trigger="fault", impact="degraded",
                           repo="ElasticsearchDeploy")
        assert R(E("defect", labels=shows), touched) == "wrap-up:fix-or-card"
        assert R(E("defect", labels=quiet), touched) == "closed:fault"
        assert R(E("improvement", labels=imp_labels(repo="ElasticsearchDeploy")),
                 touched) == "wrap-up:improvement"
        # a repo in neither the landed nor the targeted roots still is
        assert R(E("defect", labels={**shows, "repo": "HelmCharts"}), touched) == \
            "card:table"
        assert R(E("defect", labels={**quiet, "repo": "HelmCharts"}), touched) == \
            "closed:elsewhere"


# -- owed before the push ---------------------------------------------------------

def _owed(slice_dir):
    return {e["id"]: reasons for e, reasons in close_out.owed_before_push(slice_dir)}


def test_owed_before_push_lists_a_severe_entry_the_push_may_carry():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)

        def add(kind, labels, headline="h"):
            return close_out.append_entry(slice_dir, kind, headline, "b",
                                          consequence="c", labels=labels)

        add("defect", fix_labels(impact="severe"))                          # B1
        add("defect", fix_labels(impact="severe", repo="HelmCharts"))       # B2
        add("defect", fix_labels(impact="severe", repo="unknown"))          # B3
        add("defect", fix_labels(impact="severe"))                          # B4
        close_out.strike_entry(slice_dir, "B4", "fixed", commit="abc123")
        add("improvement", {**imp_labels(prevents="severe"), "impact": "severe"})  # I1
        add("defect", fix_labels(impact="broken"))                          # B5
        add("defect", None)                                                 # B6
        add("action", {"trigger": "normal-use", "impact": "severe",
                       "signal": "silent"})                                 # A1
        add("event", None)                                                  # E1
        # No state.json: every repository is the slice's own.
        assert _owed(slice_dir) == {"A1": ["impact severe"], "B1": ["impact severe"],
                                    "B2": ["impact severe"], "B3": ["impact severe"]}
        (slice_dir / "state.json").write_text(json.dumps(STATE))
        owed = close_out.owed_before_push(slice_dir)
        # a severe entry in a repository the slice never touched is not this
        # push's; an unknown repository may be; report id order
        assert [e["id"] for e, _ in owed] == ["A1", "B1", "B3"]
        assert owed[1][0]["headline"] == "h"


def test_owed_before_push_reads_a_proposal_that_asks_for_the_fix_before_the_push():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        (slice_dir / "state.json").write_text(json.dumps(STATE))

        def add(kind, labels, proposal):
            return close_out.append_entry(slice_dir, kind, "h", "b", consequence="c",
                                          labels=labels, proposal=proposal)

        b3 = ("fix now, before the push: swap the 10.1.3.x addresses in "
              "test_reader.py for documentation-range ones")
        add("defect", fix_labels(impact="degraded"), b3)                    # B1
        add("improvement", imp_labels(), "Before ANY push of this branch, "
            "drop the fixture that copies the prd dump.")                   # I1
        add("defect", fix_labels(impact="degraded"),
            "fix now if P8's branch is touched again before its push")      # B2
        add("defect", fix_labels(impact="severe", area="sensitive"), b3)    # B3
        long = "Do it before this push: " + "the address list " * 20
        add("decision", {"trigger": "normal-use", "impact": "degraded",
                         "signal": "silent"}, long)                         # D1
        add("defect", fix_labels(impact="degraded"), "push it after the release")  # B4
        before = (slice_dir / "close-out.json").read_text()
        rendered = report(slice_dir)
        owed = _owed(slice_dir)
        assert list(owed) == ["B1", "B3", "D1", "I1"]
        assert owed["B1"] == [f"proposal: {b3}"]
        # both reasons on one entry, severity first
        assert owed["B3"] == ["impact severe", f"proposal: {b3}"]
        assert owed["I1"] == ["proposal: Before ANY push of this branch, drop the "
                              "fixture that copies the prd dump."]
        (reason,) = owed["D1"]
        assert reason.startswith("proposal: Do it before this push: the address list")
        assert reason.endswith(" …") and len(reason) <= len("proposal: ") + 160
        # it reads; it never writes
        assert (slice_dir / "close-out.json").read_text() == before
        assert report(slice_dir) == rendered


def test_owed_before_push_without_a_store_is_a_report_error():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        try:
            close_out.owed_before_push(slice_dir)
            raise AssertionError("no store must raise")
        except ReportError as e:
            assert "close_out.py init" in str(e)


# -- to fix before the test phase --------------------------------------------------

def _test_slice(tmp, name="058_secret_rotation"):
    slice_dir = make_slice(tmp, name=name)
    (slice_dir / "verification.json").write_text(json.dumps({"items": [
        {"id": vid, "area": "a", "description": "d"} for vid in ("V01", "V02", "V15")]}))
    close_out.init_report(slice_dir)
    return slice_dir


def _to_test(slice_dir):
    return {e["id"]: vids for e, vids in close_out.owed_before_test(slice_dir)}


def test_owed_before_test_lists_an_entry_that_says_a_criterion_is_worded_wrong():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = _test_slice(tmp)

        def add(kind, headline, proposal=None):
            return close_out.append_entry(slice_dir, kind, headline, "b", consequence="c",
                                          labels=fix_labels(), proposal=proposal)

        # the slice-058 shape
        add("test-gap", "AnsibleSpecs 058 verification.json V15: worded against "
            "ruling D2")                                                    # T1
        add("prose", "verification.json V1 asks for a restart the plan rules out")  # P1
        add("defect", "the criterion asks more than the plan",
            "Reword V15 and V2 in slices/058_secret_rotation/verification.json "
            "to what D2 rules")                                             # B1
        add("defect", "P3 verification.json V2 names the wrong port")      # B2
        add("defect", "slice 58's verification.json V15 is worded wrong")  # B3
        add("defect", "verification.json V99 is worded wrong")             # B4
        add("defect", "V15 is worded against ruling D2",
            "reword it before the test phase")                             # B5
        before = (slice_dir / "close-out.json").read_text()
        rendered = report(slice_dir)
        owed = close_out.owed_before_test(slice_dir)
        # report id order; the criteria as verification.json spells them, in
        # number order; a phase id or the slice's own number is no other slice
        assert [(e["id"], vids) for e, vids in owed] == [
            ("B1", ["V02", "V15"]), ("B2", ["V02"]), ("B3", ["V15"]),
            ("P1", ["V01"]), ("T1", ["V15"])]
        assert owed[-1][0]["headline"].startswith("AnsibleSpecs 058 verification.json")
        # it reads; it never writes
        assert (slice_dir / "close-out.json").read_text() == before
        assert report(slice_dir) == rendered


def test_owed_before_test_leaves_an_entry_about_another_slice():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = _test_slice(tmp)
        for headline in ("slice 045's verification.json V15 is worded wrong",
                         "AnsibleSpecs 045 verification.json V15: worded wrong",
                         "slices/completed/045_x/verification.json V15 is worded wrong",
                         "verification.json V15, as Slices 45 and 58 word it",
                         "verification.json V15 contradicts slice 058 and SLICE 45"):
            close_out.append_entry(slice_dir, "defect", headline, "b", consequence="c",
                                   labels=fix_labels())
        close_out.append_entry(slice_dir, "defect", "V15 is worded wrong", "b",
                               consequence="c", labels=fix_labels(),
                               proposal="reword it as 045_secret_rotator/verification.json "
                                        "words it")
        assert _to_test(slice_dir) == {}

    # A slice folder that carries no number: any slice named is another's.
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = _test_slice(tmp, name="secret_rotation")
        close_out.append_entry(slice_dir, "defect", "058 verification.json V15 is worded "
                               "wrong", "b", consequence="c", labels=fix_labels())
        close_out.append_entry(slice_dir, "defect", "verification.json V15 is worded "
                               "wrong", "b", consequence="c", labels=fix_labels())
        assert _to_test(slice_dir) == {"B2": ["V15"]}


def test_owed_before_test_skips_struck_entries_and_the_kinds_a_test_never_fails():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = _test_slice(tmp)
        headline = "verification.json V15 is worded against ruling D2"
        for kind, labels in (("defect", fix_labels()), ("defect", fix_labels()),
                             ("action", None), ("decision", None), ("event", None),
                             ("improvement", imp_labels())):
            close_out.append_entry(slice_dir, kind, headline, "b", consequence="c",
                                   labels=labels, proposal="reword V15")
        close_out.strike_entry(slice_dir, "B2", "reworded", commit="abc123")
        assert _to_test(slice_dir) == {"B1": ["V15"]}
        # no verification.json: no criterion of the slice's is named
        (slice_dir / "verification.json").unlink()
        assert _to_test(slice_dir) == {}


def test_owed_before_test_without_a_store_is_a_report_error():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp, name="058_secret_rotation")
        try:
            close_out.owed_before_test(slice_dir)
            raise AssertionError("no store must raise")
        except ReportError as e:
            assert "close_out.py init" in str(e)


# -- append: the refusals -------------------------------------------------------

def _refused(slice_dir, argv, *needles):
    before = (slice_dir / "close-out.json").read_bytes()
    code, out, err = run_cli("append", slice_dir, *argv)
    assert code == 2 and not out, (code, out, err)
    for needle in needles:
        assert needle in err, (needle, err)
    assert (slice_dir / "close-out.json").read_bytes() == before
    return err


def test_append_refuses_a_missing_label_naming_every_flag_and_the_kind():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        err = _refused(slice_dir, with_flags(DEFECT, fix=None, repo=None),
                       "a defect carries", "missing: --fix and --repo")
        assert err.count("Error:") == 1
        _refused(slice_dir, with_flags(DEFECT, kind="prose", area=None, repo=None),
                 "a prose carries", "missing: --repo")
        # an event with an impact owes the fix, the area and the repo
        event = with_flags(DEFECT, kind="event", fix=None, area=None, repo=None)
        _refused(slice_dir, event, "missing: --fix, --area and --repo")
        _refused(slice_dir, with_flags(IMPROVEMENT, felt=None), "an improvement carries",
                 "missing: --felt")
        # an action needs trigger, impact and signal only
        code, out, _ = run_cli("append", slice_dir, *ACTION)
        assert code == 0 and out.strip() == "A1"
        # an event that describes no problem needs no fix
        code, out, _ = run_cli("append", slice_dir, *with_flags(
            DEFECT, kind="event", consequence="none", trigger="none", impact="none",
            signal="none", fix=None, area=None, repo=None))
        assert code == 0 and out.strip() == "E1"


def test_append_refuses_a_label_of_the_other_family():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        _refused(slice_dir, with_flags(IMPROVEMENT, trigger="fault"),
                 "--trigger: not a label of an improvement")
        _refused(slice_dir, with_flags(DEFECT, benefit="user", felt="in-use"),
                 "--benefit and --felt: not a label of a defect")


def test_append_refuses_an_impact_that_contradicts_the_consequence():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        for none in ("none", "None.", "**none** — cosmetic", "`none`: stale pointer"):
            _refused(slice_dir, with_flags(DEFECT, consequence=none),
                     "--impact broken over a --consequence that opens with none")
        _refused(slice_dir, with_flags(DEFECT, impact="none", signal="none"),
                 "--impact none over a --consequence that is not none")
        # "nonetheless" is not none; impact unknown goes with either
        code, _, err = run_cli("append", slice_dir, *with_flags(
            DEFECT, consequence="nonetheless the status is wrong"))
        assert code == 0, err
        code, _, err = run_cli("append", slice_dir, *with_flags(
            DEFECT, consequence="none", impact="unknown", signal="unknown"))
        assert code == 0, err
        # not checked for an improvement
        code, _, err = run_cli("append", slice_dir, *with_flags(
            IMPROVEMENT, consequence="nothing breaks, it is only slower"))
        assert code == 0, err


def test_append_refuses_a_signal_that_contradicts_the_impact():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        _refused(slice_dir, with_flags(DEFECT, consequence="none", impact="none",
                                       signal="loud"),
                 "--signal loud with --impact none")
        _refused(slice_dir, with_flags(DEFECT, signal="none"),
                 "--signal none with --impact broken")
        code, _, err = run_cli("append", slice_dir, *with_flags(
            DEFECT, impact="unknown", signal="none"))
        assert code == 0, err


def test_append_refuses_an_improvement_of_the_workflow_and_says_where_it_goes():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        _refused(slice_dir, with_flags(IMPROVEMENT, benefit="workflow"),
                 "--benefit workflow", "is not an entry", "Fieldnotes",
                 "`fieldnotes` MCP tool `post`", "category `idea`")


def test_append_refuses_a_for_that_names_no_slice_still_to_run():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        _refused(slice_dir, with_flags(DEFECT, **{"for": "99"}),
                 "--for 99: no other slice still to run has that number",
                 "--for names another slice, still to run, that should take the "
                 "entry, never the slice being run — leave it out for an entry "
                 "about this one; an entry for a slice already planned or running "
                 "comes to the operator, since that run never reads slice.md")
        # `none` clears a relabel's `for`; an append stores no "none"
        _refused(slice_dir, with_flags(DEFECT, **{"for": "none"}), "--for none",
                 "no other slice still to run")
        # a completed slice is not still to run, and neither is the slice
        # itself — which the refusal names as the slice being run
        _refused(slice_dir, with_flags(DEFECT, **{"for": "002"}), "--for 002",
                 "no other slice still to run")
        for own in ("007", "7", "007_argocd_tools_presync_hook"):
            _refused(slice_dir, with_flags(DEFECT, **{"for": own}),
                     f"--for {own} is the slice being run: --for names another "
                     "slice")
        # 12, 012 and 012_slug all name 012; the backlog counts; the folder's
        # number is what the store keeps
        for given, kept in (("12", "012"), ("012", "012"), ("012_later_slice", "012"),
                            ("31", "031")):
            code, out, err = run_cli("append", slice_dir,
                                     *with_flags(DEFECT, **{"for": given}))
            assert code == 0, err
            assert entry_of(slice_dir, out.strip())["labels"]["for"] == kept
    with tempfile.TemporaryDirectory() as tmp:
        lone = Path(tmp) / "nowhere" / "007_x"
        lone.mkdir(parents=True)
        close_out.init_report(lone)
        _refused(lone, with_flags(DEFECT, **{"for": "12"}), "no `slices` ancestor")


def plan(folder, how="state"):
    """Make a slice folder planned: a state.json, or a plan.md with a phase."""
    if how == "state":
        (folder / "state.json").write_text(json.dumps({"slice": folder.name}))
    else:
        (folder / "plan.md").write_text("# Plan\n\n## Requirements\n\n### P1 — x\n\n"
                                        "Target: app\n")


def test_slices_to_run_carries_each_slices_stage():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp, later=("012_later_slice", "013_running"))
        root = slice_dir.parent
        (root / "backlog" / "031_in_the_backlog" / "slice.md").write_text("the ask\n")
        plan(root / "013_running")
        for name in ("040_seeded", "041_header_only", "042_odd"):
            (root / "backlog" / name).mkdir()
        plan(root / "backlog" / "040_seeded", how="plan")
        # a header and `###` lines that are no phase heading are no phases
        (root / "backlog" / "041_header_only" / "plan.md").write_text(
            "# Plan\n\n## Requirements\n\n## P1 — not a phase\n### P1 - hyphen\n")
        # a plan.md that cannot be read has no phases
        (root / "backlog" / "042_odd" / "plan.md").mkdir()
        assert close_out.slices_to_run(slice_dir) == {
            12: ("012", "unplanned"), 13: ("013", "planned"), 31: ("031", "unplanned"),
            40: ("040", "planned"), 41: ("041", "unplanned"), 42: ("042", "unplanned")}
        assert close_out.slices_to_run(Path(tmp) / "007_x") is None


def test_append_takes_a_for_naming_a_planned_slice_and_routes_it_to_the_operator():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp, later=("012_later_slice", "051_planned"))
        plan(slice_dir.parent / "051_planned")
        close_out.init_report(slice_dir)
        code, out, err = run_cli("append", slice_dir, *with_flags(DEFECT, **{"for": "51"}))
        assert code == 0, err
        assert entry_of(slice_dir, out.strip())["labels"]["for"] == "051"
        code, out, err = run_cli("append", slice_dir, *with_flags(
            IMPROVEMENT, **{"for": "051_planned"}))
        assert code == 0, err
        comes = _section(report(slice_dir), "Comes to you")
        assert _heads(comes) == ["### B1 — controller: the status line is wrong",
                                 "### I1 — drop the duplicate helper"]
        assert comes.count("**Route:** " + FOR_PLANNED[1]) == 2


def test_append_normalises_label_values_and_names_the_choices():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        code, out, err = run_cli("append", slice_dir, *with_flags(
            DEFECT, kind="Test Gap", trigger="ordinary_condition", fix="Several places"))
        assert code == 0, err
        e = entry_of(slice_dir, out.strip())
        assert (e["id"], e["kind"]) == ("T1", "test-gap")
        assert e["labels"]["trigger"] == "ordinary-condition"
        assert e["labels"]["fix"] == "several-places"
        code, _, err = run_cli("append", slice_dir, *with_flags(DEFECT, impact="bad"))
        assert code == 2 and "invalid choice" in err and "degraded" in err
        # --section still takes one of the five names; --kind wins over it
        code, out, _ = run_cli("append", slice_dir, *with_flags(DEFECT, kind=None),
                               "--section", "Bugs")
        assert code == 0 and out.strip() == "B1"
        code, out, _ = run_cli("append", slice_dir, *with_flags(DEFECT, kind="prose",
                                                                area=None),
                               "--section", "Bugs")
        assert code == 0 and out.strip() == "P1"
        code, _, err = run_cli("append", slice_dir, *with_flags(DEFECT, kind=None))
        assert code == 2 and "--kind" in err


def test_append_stores_the_entry_in_the_store_shape():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        code, out, _ = run_cli("append", slice_dir, *with_flags(
            DEFECT, body="-", severity="minor",
            consequence="an operator  reads\na wrong status",
            proposal="Card it:\n  the fix  needs a design."),
                               stdin="\n  first line\n\nsecond paragraph  \n\n")
        assert code == 0 and out.strip() == "B1"
        data = store(slice_dir)
        assert data["store"] == 1 and data["slice"] == "007_argocd_tools_presync_hook"
        assert data["closed"] is None
        assert data["entries"] == [{
            "id": "B1", "kind": "defect", "grade": "minor",
            "headline": "controller: the status line is wrong",
            "body": ["  first line", "", "second paragraph"],
            "consequence": "an operator reads a wrong status",
            "proposal": "Card it: the fix needs a design.",
            "evidence": "witnessed", "author": "code-reviewer, P3 r1", "by": None,
            "labels": {"trigger": "ordinary-condition", "impact": "broken",
                       "signal": "silent", "fix": "design", "area": "sensitive",
                       "repo": "KubeCoder"},
            "notes": [], "wrap_up": None, "strike": None, "ruling": None}]
        # the proposal stands right after the Consequence
        assert list(data["entries"][0])[5:7] == ["consequence", "proposal"]
        raw = (slice_dir / "close-out.json").read_text()
        assert raw.endswith("}\n") and raw == json.dumps(data, indent=2,
                                                         ensure_ascii=False) + "\n"
        # no temp file left beside it
        assert sorted(p.name for p in slice_dir.iterdir()) == ["close-out.json",
                                                               "close-out.md"]
        # without --proposal, a defect stores none
        code, out, _ = run_cli("append", slice_dir, *DEFECT)
        assert entry_of(slice_dir, out.strip())["proposal"] is None


def test_append_asks_a_proposal_of_an_action_a_decision_and_an_improvement():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        for base, article in ((ACTION, "an action"), (DECISION, "a decision"),
                              (IMPROVEMENT, "an improvement")):
            for missing in (None, " \n "):
                _refused(slice_dir, with_flags(base, proposal=missing),
                         f"Error: {article} needs --proposal: what you would do about "
                         "it and why, in a sentence or two")
        # said with the label refusals, in one error
        err = _refused(slice_dir, with_flags(IMPROVEMENT, proposal=None, felt=None),
                       "missing: --felt", "an improvement needs --proposal")
        assert err.count("Error:") == 1
        # a defect, prose, a test gap and an event owe none
        for argv in (DEFECT, with_flags(DEFECT, kind="prose", area=None),
                     with_flags(DEFECT, kind="test-gap"),
                     with_flags(ACTION, kind="event", proposal=None, consequence="none",
                                trigger="none", impact="none", signal="none")):
            code, _, err = run_cli("append", slice_dir, *argv)
            assert code == 0, err
        # the loops' path refuses nothing
        assert close_out.append_entry(slice_dir, "action", "Do X", "b",
                                      consequence="none") == "A1"
        assert entry_of(slice_dir, "A1")["proposal"] is None
        assert close_out.append_entry(slice_dir, "action", "Do Y", "b", consequence="none",
                                      proposal=" Do it\n now. ") == "A2"
        assert entry_of(slice_dir, "A2")["proposal"] == "Do it now."


def test_provenance_splits_the_evidence_class_off():
    split = close_out._split_provenance
    assert split("witnessed — code-reviewer, P3 r1") == ("witnessed", "code-reviewer, P3 r1")
    assert split("read, plan-reviewer r2") == ("read", "plan-reviewer r2")
    assert split("Read: P2 r1 F3") == ("read", "P2 r1 F3")
    assert split("read-only probe of P2") == (None, "read-only probe of P2")
    assert split("P3 review r1 F3") == (None, "P3 review r1 F3")
    assert split(None) == (None, None)


# -- the loops' path: the labels the tool gives -----------------------------------

def test_the_loops_entries_get_the_tools_labels_and_route_from_them():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        e1 = close_out.append_entry(slice_dir, "Notable events", "P3 bailed blocked",
                                    "venue off the wire",
                                    consequence="none — the resume took it up",
                                    provenance="witnessed — the driver")
        e2 = close_out.append_entry(slice_dir, "Notable events", "a finding was refuted",
                                    "b", consequence="the operator should check X")
        a1 = close_out.append_entry(slice_dir, "Outstanding actions",
                                    "Push HelmCharts by hand", "b",
                                    consequence="none in this run — the hold stands")
        d1 = close_out.append_entry(slice_dir, "Open questions and rulings", "which?",
                                    "b", consequence="the rollout waits on it")
        b1 = close_out.append_entry(slice_dir, "Bugs", "a bug", "b", consequence="c")
        s1 = close_out.append_entry(slice_dir, "Suggestions", "an idea", "b",
                                    consequence="none")
        assert (e1, e2, a1, d1, b1, s1) == ("E1", "E2", "A1", "D1", "B1", "I1")
        none = dict.fromkeys(("trigger", "impact", "signal"), "none")
        unknown = dict.fromkeys(("trigger", "impact", "signal"), "unknown")
        assert entry_of(slice_dir, "E1")["labels"] == none
        assert entry_of(slice_dir, "E2")["labels"] == unknown
        assert entry_of(slice_dir, "A1")["labels"] == none
        assert entry_of(slice_dir, "D1")["labels"] == unknown
        assert entry_of(slice_dir, "B1")["labels"] is None
        assert entry_of(slice_dir, "I1")["labels"] is None
        # the event that describes no problem is the record; the other is
        # looked at by the wrap-up
        close_out.render_report(slice_dir)
        text = report(slice_dir)
        record = text[text.index("## Record"):]
        assert "### E1 — P3 bailed blocked" in record
        wrap = text[text.index("## For the wrap-up"):text.index("## Unlabelled")]
        assert "### E2 — a finding was refuted" in wrap
        assert "**Route:** the wrap-up — look: its trigger and impact are unknown" in wrap
        # the loops' path refuses nothing about labels
        assert close_out.append_entry(slice_dir, "defect", "x", "b", consequence="none",
                                      labels={"impact": "broken"}) == "B2"


def test_append_entry_takes_a_kind_or_one_of_the_five_sections_and_nothing_else():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        for bad in ("Summary", "Defects", "bug"):
            try:
                close_out.append_entry(slice_dir, bad, "x", "y")
                raise AssertionError(f"{bad} must raise")
            except ReportError as e:
                assert "unknown kind" in str(e)
        try:
            close_out.append_entry(slice_dir, "Bugs", "x", "y", severity="Blocker")
            raise AssertionError("reviewer severities never reach the report")
        except ReportError:
            pass
        assert store(slice_dir)["entries"] == []


def test_append_without_a_store_or_report_says_run_init():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        try:
            close_out.append_entry(slice_dir, "Bugs", "x", "y")
            raise AssertionError("no store must raise")
        except ReportError as e:
            assert "close_out.py init" in str(e)
        code, _, err = run_cli("list", slice_dir / "close-out.md")
        assert code == 2 and "does not exist" in err and "init" in err


# -- ids ----------------------------------------------------------------------------

def test_ids_are_minted_per_letter_struck_counted_and_never_renamed():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        ids = [run_cli("append", slice_dir, *argv)[1].strip() for argv in (
            DEFECT, IMPROVEMENT, DEFECT, with_flags(DEFECT, kind="prose", area=None))]
        assert ids == ["B1", "I1", "B2", "P1"]
        close_out.strike_entry(slice_dir, "B2", "duplicate of B1")
        assert run_cli("append", slice_dir, *DEFECT)[1].strip() == "B3"
        code, _, err = run_cli("relabel", slice_dir, "B3", "--by", "wrap-up",
                               "--note", "it is text, not code", "--kind", "prose")
        assert code == 0, err
        e = entry_of(slice_dir, "B3")
        assert e["kind"] == "prose"
        # the next prose is P2, the next defect B4: the id stays B3
        assert run_cli("append", slice_dir, *with_flags(DEFECT, kind="prose",
                                                        area=None))[1].strip() == "P2"
        assert run_cli("append", slice_dir, *DEFECT)[1].strip() == "B4"


# -- note, strike ------------------------------------------------------------------

def test_note_adds_a_dated_signed_paragraph_even_to_a_struck_entry():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        run_cli("append", slice_dir, *DEFECT)
        para = close_out.add_note(slice_dir, "B1", " consult  1 ",
                                  "  the premise moved:\nP4 rewrote it.\n",
                                  date="2026-08-17")
        assert para == "consult 1, 2026-08-17 — the premise moved:\nP4 rewrote it."
        assert entry_of(slice_dir, "B1")["notes"] == [
            {"by": "consult 1", "date": "2026-08-17",
             "text": ["the premise moved:", "P4 rewrote it."]}]
        close_out.strike_entry(slice_dir, "B1", "fixed")
        code, out, _ = run_cli("note", slice_dir, "B1", "--by", "op", "--text", "-",
                               stdin="still true\n")
        assert code == 0 and out.strip() == "B1 noted"
        assert len(entry_of(slice_dir, "B1")["notes"]) == 2
        for eid, text, date in (("B9", "t", None), ("X", "t", None), ("B1", " \n", None),
                                ("B1", "t", "17-08-2026")):
            try:
                close_out.add_note(slice_dir, eid, "who", text, date=date)
                raise AssertionError(f"{eid}/{text!r}/{date} must raise")
            except ReportError:
                pass
        assert re.fullmatch(r"op, \d{4}-\d{2}-\d{2} — t",
                            close_out.add_note(slice_dir, "B1", "op", "t"))


def test_strike_stores_the_reason_and_commit_and_shows_them_in_the_heading():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        run_cli("append", slice_dir, *with_flags(DEFECT, severity="nit"))
        run_cli("append", slice_dir, *DEFECT)
        code, out, _ = run_cli("strike", slice_dir, "B1", "--reason",
                               " resolved by  P4: suite re-run", "--by", "consult 1",
                               "--commit", "19640d9", "--date", "2026-09-30")
        assert code == 0
        assert out.strip() == ("### ~~B1 — controller: the status line is wrong · nit~~ — "
                               "resolved by P4: suite re-run (19640d9); struck by consult 1")
        assert entry_of(slice_dir, "B1")["strike"] == {
            "reason": "resolved by P4: suite re-run", "by": "consult 1",
            "date": "2026-09-30", "commit": "19640d9"}
        # a reason that names the commit already does not repeat it
        heading = close_out.strike_entry(slice_dir, "B2", "resolved by P4 (19640d9)",
                                         commit="19640d9")
        assert heading.endswith("~~ — resolved by P4 (19640d9)")
        code, _, err = run_cli("strike", slice_dir, "B1", "--reason", "again")
        assert code == 2 and "already struck" in err
        code, _, err = run_cli("strike", slice_dir, "B9", "--reason", "x")
        assert code == 2 and "no entry B9" in err


# -- relabel ---------------------------------------------------------------------

def test_relabel_merges_the_labels_and_leaves_a_note_saying_what_changed():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        run_cli("append", slice_dir, *DEFECT)
        code, out, err = run_cli("relabel", slice_dir, "B1", "--by", "wrap-up",
                                 "--note", "the code shows one call site",
                                 "--fix", "one-edit", "--area", "plain",
                                 "--date", "2026-09-30")
        assert code == 0, err
        assert out.strip() == ("wrap-up, 2026-09-30 — relabelled (fix: design → one-edit, "
                               "area: sensitive → plain): the code shows one call site")
        e = entry_of(slice_dir, "B1")
        assert e["labels"]["fix"] == "one-edit" and e["labels"]["area"] == "plain"
        assert e["labels"]["trigger"] == "ordinary-condition"
        assert e["notes"][-1]["relabel"] == {"fix": ["design", "one-edit"],
                                             "area": ["sensitive", "plain"]}
        # a relabel that changes nothing is refused
        code, _, err = run_cli("relabel", slice_dir, "B1", "--by", "w", "--note", "n",
                               "--fix", "one-edit")
        assert code == 2 and "changes nothing" in err


def test_relabel_applies_the_refusals_but_not_the_consequence_check():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        run_cli("append", slice_dir, *with_flags(DEFECT, consequence="none",
                                                 impact="none", signal="none"))
        run_cli("append", slice_dir, *IMPROVEMENT)
        relabel = ("relabel", slice_dir, "B1", "--by", "wrap-up", "--note", "n")
        # the Consequence is the author's text: an impact over "none" is taken
        code, _, err = run_cli(*relabel, "--impact", "broken")
        assert code == 0, err
        code, _, err = run_cli(*relabel, "--benefit", "user")
        assert code == 2 and "--benefit: not a label of a defect" in err
        code, _, err = run_cli(*relabel, "--for", "77")
        assert code == 2 and "--for 77" in err
        code, _, err = run_cli("relabel", slice_dir, "I1", "--by", "w", "--note", "n",
                               "--benefit", "workflow")
        assert code == 2 and "Fieldnotes" in err
        # moving to the other family drops the old family's labels, and asks
        # for the new one's
        code, _, err = run_cli("relabel", slice_dir, "I1", "--by", "w", "--note", "n",
                               "--kind", "defect")
        assert code == 2 and "missing: --trigger, --impact, --signal and --fix" in err
        code, _, err = run_cli("relabel", slice_dir, "I1", "--by", "w", "--note", "n",
                               "--kind", "defect", "--trigger", "fault", "--impact",
                               "degraded", "--signal", "loud", "--fix", "design")
        assert code == 0, err
        e = entry_of(slice_dir, "I1")
        assert e["id"] == "I1" and e["kind"] == "defect"
        assert set(e["labels"]) == {"trigger", "impact", "signal", "fix", "area", "repo"}
        assert e["notes"][-1]["relabel"]["kind"] == ["improvement", "defect"]


def test_relabel_to_a_kind_drops_the_labels_it_does_not_carry_and_names_them():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        run_cli("append", slice_dir, *DEFECT)
        code, out, err = run_cli("relabel", slice_dir, "B1", "--by", "wrap-up",
                                 "--note", "it is a comment", "--kind", "prose",
                                 "--date", "2026-10-12")
        assert code == 0, err
        assert out.strip() == ("wrap-up, 2026-10-12 — relabelled (kind: defect → prose, "
                               "area: sensitive → —; dropped area, which a prose does "
                               "not carry): it is a comment")
        e = entry_of(slice_dir, "B1")
        assert e["kind"] == "prose" and "area" not in e["labels"]
        assert e["notes"][-1]["relabel"] == {"kind": ["defect", "prose"],
                                             "area": ["sensitive", None]}
        assert "sensitive area" not in close_out.render_report(slice_dir)
        # back to a defect, the area is asked for again
        code, _, err = run_cli("relabel", slice_dir, "B1", "--by", "w", "--note", "n",
                               "--kind", "defect")
        assert code == 2 and "missing: --area" in err


def test_relabel_gives_an_unlabelled_entry_its_first_labels():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        close_out.append_entry(slice_dir, "Bugs", "an old bug", "b", consequence="c")
        base = ("relabel", slice_dir, "B1", "--by", "wrap-up", "--note", "from its text")
        code, _, err = run_cli(*base, "--trigger", "fault")
        assert code == 2 and "missing: --impact, --signal, --fix, --area and --repo" in err
        code, out, err = run_cli(*base, "--trigger", "fault", "--impact", "degraded",
                                 "--signal", "silent", "--fix", "design", "--area",
                                 "plain", "--repo", "KubeCoder")
        assert code == 0, err
        assert "trigger: — → fault" in out
        assert close_out.route(entry_of(slice_dir, "B1"))[0] == "closed:fault"


def test_relabel_dry_run_prints_the_note_and_the_route_and_writes_nothing():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        run_cli("append", slice_dir, *DEFECT)
        before = _files(slice_dir)
        relabel = ("relabel", slice_dir, "B1", "--by", "wrap-up", "--note", "one call site",
                   "--date", "2026-10-13")
        code, out, err = run_cli(*relabel, "--fix", "one-edit", "--area", "plain",
                                 "--dry-run")
        assert code == 0, err
        assert out == ("wrap-up, 2026-10-13 — relabelled (fix: design → one-edit, area: "
                       "sensitive → plain): one call site\n"
                       "route: For the wrap-up — the wrap-up — fix\n")
        assert _files(slice_dir) == before
        # what relabel refuses, the dry run refuses — and writes nothing either
        for flags, needle in ((("--benefit", "user"), "--benefit: not a label of a defect"),
                              (("--fix", "design"), "changes nothing"),
                              (("--for", "77"), "--for 77")):
            code, out, err = run_cli(*relabel, *flags, "--dry-run")
            assert code == 2 and not out and needle in err, (flags, err)
            assert _files(slice_dir) == before
        # the Consequence check stays off, as on relabel: an impact of none over
        # a Consequence that is not none is taken, and closes the entry
        code, out, err = run_cli(*relabel, "--impact", "none", "--signal", "none",
                                 "--dry-run")
        assert code == 0, err
        assert out.endswith("\nroute: Closed — closed — it has no impact\n")
        assert _files(slice_dir) == before
        # the relabel itself leaves the note the dry run printed
        code, real, err = run_cli(*relabel, "--fix", "one-edit", "--area", "plain")
        assert code == 0, err
        assert real == ("wrap-up, 2026-10-13 — relabelled (fix: design → one-edit, area: "
                        "sensitive → plain): one call site\n")
        assert entry_of(slice_dir, "B1")["labels"]["fix"] == "one-edit"


def test_relabel_dry_run_prints_the_route_a_for_naming_a_planned_slice_gives():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp, later=("012_later_slice", "051_planned"))
        plan(slice_dir.parent / "051_planned")
        close_out.init_report(slice_dir)
        run_cli("append", slice_dir, *DEFECT)
        before = _files(slice_dir)
        code, out, err = run_cli("relabel", slice_dir, "B1", "--by", "wrap-up", "--note",
                                 "slice 051 takes it", "--for", "51", "--date",
                                 "2026-10-14", "--dry-run")
        assert code == 0, err
        assert out == ("wrap-up, 2026-10-14 — relabelled (for: — → 051): slice 051 takes it\n"
                       f"route: Comes to you — {FOR_PLANNED[1]}\n")
        assert _files(slice_dir) == before


def test_relabel_for_none_clears_for_and_unnote_puts_it_back():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        run_cli("append", slice_dir, *with_flags(DEFECT, **{"for": "12"}))
        before, text = store(slice_dir), report(slice_dir)
        relabel = ("relabel", slice_dir, "B1", "--by", "wrap-up", "--date", "2026-10-14")
        code, out, err = run_cli(*relabel, "--note", "it is this slice's", "--for", "none")
        assert code == 0, err
        assert out.strip() == ("wrap-up, 2026-10-14 — relabelled (for: 012 → —): it is "
                               "this slice's")
        e = entry_of(slice_dir, "B1")
        assert "for" not in e["labels"]
        assert e["notes"][-1]["relabel"] == {"for": ["012", None]}
        assert "fold" not in report(slice_dir)
        # nothing left to clear: a relabel that changes nothing
        code, _, err = run_cli(*relabel, "--note", "n", "--for", "NONE")
        assert code == 2 and "changes nothing" in err
        try:
            close_out.relabel_entry(slice_dir, "B1", "w", "n", labels={"for": "none"})
            raise AssertionError("clearing a `for` the entry lacks must raise")
        except ReportError as e:
            assert "changes nothing" in str(e)
        # the author withdraws it, and the label comes back
        code, _, err = run_cli("unnote", slice_dir, "B1", "--by", "wrap-up")
        assert code == 0, err
        assert store(slice_dir)["entries"] == before["entries"]
        assert report(slice_dir) == text
        # the Python API clears it the same way
        close_out.relabel_entry(slice_dir, "B1", "w", "n", labels={"for": "none"})
        assert "for" not in entry_of(slice_dir, "B1")["labels"]


def test_a_relabel_checks_for_only_where_the_call_gives_one():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        root = slice_dir.parent
        close_out.init_report(slice_dir)
        run_cli("append", slice_dir, *with_flags(DEFECT, **{"for": "12"}))
        # 012 runs and is completed; the stored `for` names no slice to run
        (root / "012_later_slice").rename(root / "completed" / "012_later_slice")
        relabel = ("relabel", slice_dir, "B1", "--by", "wrap-up", "--note", "n")
        code, _, err = run_cli(*relabel, "--impact", "degraded")
        assert code == 0, err
        assert entry_of(slice_dir, "B1")["labels"]["for"] == "012"
        # a `for` the call gives is checked, the slice that ran refused
        for target in ("12", "77"):
            code, _, err = run_cli(*relabel, "--for", target)
            assert code == 2 and f"--for {target}: no other slice still to run" in err
        code, _, err = run_cli(*relabel, "--for", "31")
        assert code == 0, err
        assert entry_of(slice_dir, "B1")["labels"]["for"] == "031"


# -- unnote, unstrike: an author takes back what is not committed ------------------

def git(cwd, *args):
    """git with an identity and no signing, whatever the host's config says."""
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t",
                    "-c", "commit.gpgsign=false", *args],
                   cwd=cwd, check=True, capture_output=True)


def commit_store(slice_dir, text=None):
    """Commit the slice's store in the spec repo around it, made one first
    where it is not; with `text`, that is what the commit holds, the store
    on disk kept as it is."""
    spec = slice_dir.parent.parent
    if not (spec / ".git").exists():
        git(spec, "init", "-q")
    path = slice_dir / "close-out.json"
    kept = path.read_bytes()
    if text is not None:
        path.write_text(text)
    git(spec, "add", str(path))
    git(spec, "commit", "-q", "--no-verify", "-m", "close-out")
    path.write_bytes(kept)


def test_unstrike_withdraws_its_strikers_strike_and_striking_again_amends_it():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        run_cli("append", slice_dir, *DEFECT)
        live = report(slice_dir)
        run_cli("strike", slice_dir, "B1", "--reason", "fixed", "--by", "consult 1")
        code, _, err = run_cli("strike", slice_dir, "B1", "--reason", "fixed in abc123",
                               "--by", "consult 1")
        assert code == 2 and "B1 is already struck: ~~B1 — " in err
        assert ("Its striker withdraws it while it is not committed — `unstrike B1 --by "
                "consult 1` — and strikes again.") in err
        code, out, err = run_cli("unstrike", slice_dir, "B1", "--by", " consult  1 ")
        assert code == 0, err
        assert out == "### B1 — controller: the status line is wrong\n"
        assert entry_of(slice_dir, "B1")["strike"] is None
        assert report(slice_dir) == live
        # the amendment: struck again, with the words it should have had
        code, _, err = run_cli("strike", slice_dir, "B1", "--reason", "fixed in abc123",
                               "--by", "consult 1")
        assert code == 0, err
        assert entry_of(slice_dir, "B1")["strike"]["reason"] == "fixed in abc123"
        assert entry_of(slice_dir, "B1")["notes"] == []
        # nothing to withdraw on a live entry, and --by is required
        run_cli("append", slice_dir, *DEFECT)
        code, _, err = run_cli("unstrike", slice_dir, "B2", "--by", "consult 1")
        assert code == 2 and "B2 is not struck" in err
        code, _, _ = run_cli("unstrike", slice_dir, "B1")
        assert code == 2
        try:
            close_out.unstrike_entry(slice_dir, "B1", " ")
            raise AssertionError("an empty --by must raise")
        except ReportError as e:
            assert "unstrike needs --by" in str(e)


def test_unstrike_is_refused_to_another_by_a_strike_without_one_and_the_rulings():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        for _ in range(3):
            run_cli("append", slice_dir, *DEFECT)                              # B1–B3
        close_out.strike_entry(slice_dir, "B1", "fixed", by="consult 1")
        close_out.strike_entry(slice_dir, "B2", "fixed")
        close_out.rule_entry(slice_dir, "B3", words="fix it", did="fixed in abc123")
        before = _files(slice_dir)
        for eid, by, needles in (
                ("B1", "wrap-up", ["B1 was struck by consult 1, not wrap-up: only its "
                                   "striker withdraws a strike"]),
                ("B2", "consult 1", ["B2 stays struck: a strike made without --by has no "
                                     "author to take it back; a note adds to it"]),
                ("B3", "the operator's ruling",
                 ["B3 stays struck: the operator's ruling (`rule --did`) struck it, and "
                  "the ruling owns it"])):
            code, _, err = run_cli("unstrike", slice_dir, eid, "--by", by)
            assert code == 2, (eid, err)
            for needle in needles:
                assert needle in err, (needle, err)
            assert _files(slice_dir) == before
        # striking again says the same, in place of naming unstrike
        code, _, err = run_cli("strike", slice_dir, "B2", "--reason", "r")
        assert code == 2 and "is already struck" in err
        assert ("A strike made without --by has no author to take it back; a note adds "
                "to it.") in err and "unstrike" not in err
        code, _, err = run_cli("strike", slice_dir, "B3", "--reason", "r")
        assert code == 2 and "the ruling owns it; a note adds to it." in err
        # a closed report's strikes are made without --by
        run_cli("append", slice_dir, *DEFECT)                                   # B4
        close_out.close_report(slice_dir, "all done")
        code, _, err = run_cli("unstrike", slice_dir, "B4", "--by", "the operator")
        assert code == 2 and "has no author to take it back" in err


def test_a_committed_strike_stays_and_a_later_one_is_withdrawn():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        run_cli("append", slice_dir, *DEFECT)
        run_cli("append", slice_dir, *DEFECT)
        close_out.strike_entry(slice_dir, "B1", "fixed", by="consult 1")
        commit_store(slice_dir)
        before = _files(slice_dir)
        code, _, err = run_cli("unstrike", slice_dir, "B1", "--by", "consult 1")
        assert code == 2
        assert "B1's strike is committed, and a committed strike stays; a note adds" in err
        assert _files(slice_dir) == before
        close_out.strike_entry(slice_dir, "B2", "fixed", by="consult 1")
        code, _, err = run_cli("unstrike", slice_dir, "B2", "--by", "consult 1")
        assert code == 0, err
        assert entry_of(slice_dir, "B2")["strike"] is None
        assert entry_of(slice_dir, "B1")["strike"]["by"] == "consult 1"


def test_unnote_withdraws_the_authors_latest_note_and_skips_another_authors_later_one():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        run_cli("append", slice_dir, *DEFECT)
        live = report(slice_dir)
        for by, text in (("consult 1", "first"), ("consult 1", "second"),
                         ("wrap-up", "theirs")):
            run_cli("note", slice_dir, "B1", "--by", by, "--text", text,
                    "--date", "2026-10-13")
        code, out, err = run_cli("unnote", slice_dir, "B1", "--by", "consult 1")
        assert code == 0, err
        assert out == "B1 unnoted: consult 1, 2026-10-13 — second\n"
        assert [n["text"] for n in entry_of(slice_dir, "B1")["notes"]] == [["first"],
                                                                         ["theirs"]]
        assert "second" not in close_out.show_view(slice_dir, ["B1"])
        code, out, _ = run_cli("unnote", slice_dir, "B1", "--by", "consult 1")
        assert code == 0 and out == "B1 unnoted: consult 1, 2026-10-13 — first\n"
        before = _files(slice_dir)
        code, _, err = run_cli("unnote", slice_dir, "B1", "--by", "consult 1")
        assert code == 2
        assert "B1 holds no note consult 1 wrote with `note` or `relabel`" in err
        assert _files(slice_dir) == before
        code, _, _ = run_cli("unnote", slice_dir, "B1", "--by", "wrap-up")
        assert code == 0 and entry_of(slice_dir, "B1")["notes"] == []
        assert report(slice_dir) == live
        code, _, err = run_cli("unnote", slice_dir, "B9", "--by", "wrap-up")
        assert code == 2 and "no entry B9" in err


def test_unnote_never_takes_a_history_note():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        run_cli("append", slice_dir, *DEFECT)                                   # B1
        run_cli("append", slice_dir, *DEFECT)                                   # B2
        run_cli("append", slice_dir, *DECISION)                                 # D1
        # a replaced proposal is kept as a note signed by who replaced it
        close_out.propose_entry(slice_dir, "B1", "wrap-up", "Card it.")
        close_out.add_note(slice_dir, "B1", "wrap-up", "mine", date="2026-10-13")
        close_out.propose_entry(slice_dir, "B1", "wrap-up", "Fix it now.")
        assert entry_of(slice_dir, "B1")["notes"][-1]["history"] == "proposal"
        code, out, err = run_cli("unnote", slice_dir, "B1", "--by", "wrap-up")
        assert code == 0, err
        assert out == "B1 unnoted: wrap-up, 2026-10-13 — mine\n"
        assert [n["text"] for n in entry_of(slice_dir, "B1")["notes"]] == [
            ["proposal replaced — was: Card it."]]
        code, _, err = run_cli("unnote", slice_dir, "B1", "--by", "wrap-up")
        assert code == 2 and "B1 holds no note wrap-up wrote" in err
        # the wrap-up's first mark, kept when a second replaces it
        close_out.request_card(slice_dir, "B2", "wrap-up", "needs a design")
        close_out.leave_entry(slice_dir, "B2", "wrap-up", "dead code after all")
        assert entry_of(slice_dir, "B2")["notes"][-1]["history"] == "wrap-up"
        code, _, err = run_cli("unnote", slice_dir, "B2", "--by", "wrap-up")
        assert code == 2 and "B2 holds no note wrap-up wrote" in err
        # the operator's earlier words, kept when a ruling replaces them
        close_out.rule_entry(slice_dir, "D1", words="A")
        close_out.rule_entry(slice_dir, "D1", words="B", mode="replace")
        code, _, err = run_cli("unnote", slice_dir, "D1", "--by", "the operator")
        assert code == 2 and "D1 holds no note the operator wrote" in err
        # history notes render as every note does
        shown = close_out.show_view(slice_dir, ["B1", "D1"])
        assert "— proposal replaced — was: Card it." in shown
        assert "the operator, " in shown and "— ruled earlier: A" in shown


def test_a_committed_note_stays_and_a_later_one_is_withdrawn():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        run_cli("append", slice_dir, *DEFECT)
        note = ("note", slice_dir, "B1", "--by", "consult 1", "--date", "2026-10-13",
                "--text")
        run_cli(*note, "committed")
        # a repository with no commit yet holds nothing
        git(slice_dir.parent.parent, "init", "-q")
        code, _, err = run_cli("unnote", slice_dir, "B1", "--by", "consult 1")
        assert code == 0, err
        run_cli(*note, "committed")
        commit_store(slice_dir)
        before = _files(slice_dir)
        code, _, err = run_cli("unnote", slice_dir, "B1", "--by", "consult 1")
        assert code == 2
        assert ("consult 1's latest note on B1 is committed, and a committed note stays; "
                "a new note adds to it — consult 1, 2026-10-13 — committed") in err
        assert _files(slice_dir) == before
        # a later note is withdrawn — and so is a retry of the committed one
        for text in ("later", "committed"):
            run_cli(*note, text)
            code, out, err = run_cli("unnote", slice_dir, "B1", "--by", "consult 1")
            assert code == 0, err
            assert out == f"B1 unnoted: consult 1, 2026-10-13 — {text}\n"
            assert len(entry_of(slice_dir, "B1")["notes"]) == 1
        # a HEAD store that cannot be read refuses rather than lets through
        commit_store(slice_dir, text="not json\n")
        run_cli(*note, "after")
        code, _, err = run_cli("unnote", slice_dir, "B1", "--by", "consult 1")
        assert code == 2 and "HEAD's close-out.json in " in err
        assert "is not a close-out store" in err
        assert len(entry_of(slice_dir, "B1")["notes"]) == 2


def test_a_git_that_hangs_refuses_the_withdrawal_and_no_git_commits_nothing():
    def hang(argv, **kw):
        raise subprocess.TimeoutExpired(argv, kw.get("timeout"))

    def missing(argv, **kw):
        raise FileNotFoundError(argv[0])

    real = close_out.subprocess.run
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        run_cli("append", slice_dir, *DEFECT)
        close_out.add_note(slice_dir, "B1", "consult 1", "t")
        close_out.strike_entry(slice_dir, "B1", "fixed", by="consult 1")
        before = _files(slice_dir)
        try:
            close_out.subprocess.run = hang
            for verb in ("unnote", "unstrike"):
                code, _, err = run_cli(verb, slice_dir, "B1", "--by", "consult 1")
                assert code == 2, (verb, err)
                assert f"did not answer within {close_out.GIT_SHOW_TIMEOUT}s" in err
                assert "nothing was withdrawn" in err
                assert _files(slice_dir) == before
            close_out.subprocess.run = missing
            for verb in ("unnote", "unstrike"):
                code, _, err = run_cli(verb, slice_dir, "B1", "--by", "consult 1")
                assert code == 0, (verb, err)
        finally:
            close_out.subprocess.run = real
        b1 = entry_of(slice_dir, "B1")
        assert b1["notes"] == [] and b1["strike"] is None


def test_unnote_of_a_relabel_puts_back_the_kind_and_the_labels():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        run_cli("append", slice_dir, *DEFECT)                                   # B1
        close_out.append_entry(slice_dir, "Bugs", "an old bug", "b",
                               consequence="c")                                 # B2
        close_out.append_entry(slice_dir, "action", "do it", "b",
                               consequence="c")                                 # A1
        relabels = (
            ("B1", ["--fix", "one-edit", "--area", "plain"]),
            # a new kind, the label it does not carry dropped
            ("B1", ["--kind", "prose"]),
            # an unlabelled entry's first labels
            ("B2", ["--trigger", "fault", "--impact", "degraded", "--signal", "silent",
                    "--fix", "design", "--area", "plain", "--repo", "KubeCoder"]),
            # the labels the tool gave an action a loop entered
            ("A1", ["--impact", "degraded"]))
        for eid, flags in relabels:
            before, text = store(slice_dir), report(slice_dir)
            code, _, err = run_cli("relabel", slice_dir, eid, "--by", "wrap-up",
                                   "--note", "n", *flags)
            assert code == 0, (eid, flags, err)
            assert entry_of(slice_dir, eid) != next(e for e in before["entries"]
                                                    if e["id"] == eid)
            code, out, err = run_cli("unnote", slice_dir, eid, "--by", "wrap-up")
            assert code == 0, (eid, flags, err)
            assert out.startswith(f"{eid} unnoted: wrap-up, ")
            assert store(slice_dir)["entries"] == before["entries"], (eid, flags)
            assert report(slice_dir) == text, (eid, flags)
        assert entry_of(slice_dir, "B2")["labels"] is None
        assert close_out.route(entry_of(slice_dir, "B2"))[0] == "unlabelled"
        assert entry_of(slice_dir, "A1")["labels"] == close_out.tool_labels("action", "c")


def test_unnote_of_a_relabel_is_refused_when_a_later_relabel_changed_it_again():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        run_cli("append", slice_dir, *DEFECT)

        def relabel(by, *flags):
            code, _, err = run_cli("relabel", slice_dir, "B1", "--by", by, "--note", "n",
                                   "--date", "2026-10-13", *flags)
            assert code == 0, err

        def labels():
            e = entry_of(slice_dir, "B1")
            return e["kind"], e["labels"]

        original = labels()
        relabel("w1", "--fix", "one-edit")
        relabel("w2", "--fix", "several-places")
        before = _files(slice_dir)
        code, _, err = run_cli("unnote", slice_dir, "B1", "--by", "w1")
        assert code == 2
        assert ("B1: w1's relabel is not withdrawn — a later relabel, w2's of 2026-10-13, "
                "changed fix again; that one is withdrawn first") in err
        assert _files(slice_dir) == before
        # in order, both come back
        assert run_cli("unnote", slice_dir, "B1", "--by", "w2")[0] == 0
        assert labels()[1]["fix"] == "one-edit"
        assert run_cli("unnote", slice_dir, "B1", "--by", "w1")[0] == 0
        assert labels() == original
        # a later relabel of another label leaves this one free to go
        relabel("w1", "--fix", "one-edit")
        relabel("w2", "--trigger", "fault")
        assert run_cli("unnote", slice_dir, "B1", "--by", "w1")[0] == 0
        assert labels()[1]["fix"] == "design" and labels()[1]["trigger"] == "fault"
        assert run_cli("unnote", slice_dir, "B1", "--by", "w2")[0] == 0
        assert labels() == original
        # across a change of kind, any later relabel holds it
        relabel("w1", "--kind", "prose")
        relabel("w2", "--impact", "degraded")
        code, _, err = run_cli("unnote", slice_dir, "B1", "--by", "w1")
        assert code == 2 and "relabelled it across a change of its kind" in err
        assert run_cli("unnote", slice_dir, "B1", "--by", "w2")[0] == 0
        assert run_cli("unnote", slice_dir, "B1", "--by", "w1")[0] == 0
        assert labels() == original
        # a store that no longer carries what the relabel left is not undone
        relabel("w1", "--fix", "one-edit")
        data = store(slice_dir)
        data["entries"][0]["labels"]["fix"] = "unknown"
        (slice_dir / "close-out.json").write_text(json.dumps(data))
        code, _, err = run_cli("unnote", slice_dir, "B1", "--by", "w1")
        assert code == 2
        assert ("it left fix one-edit, and the entry carries unknown now") in err


# -- amend: the appender corrects an entry that is not committed -------------------

BY = "code-reviewer P3 r1"


def _amend(slice_dir, eid, *flags, by=BY, stdin=None):
    return run_cli("amend", slice_dir, eid, *(("--by", by) if by is not None else ()),
                   *flags, stdin=stdin)


def _amend_refused(slice_dir, eid, flags, *needles, by=BY):
    before = _files(slice_dir)
    code, out, err = _amend(slice_dir, eid, *flags, by=by)
    assert code == 2 and not out, (code, out, err)
    for needle in needles:
        assert needle in err, (needle, err)
    assert _files(slice_dir) == before
    return err


def test_append_by_records_the_appender_and_without_it_the_entry_has_none():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        code, out, err = run_cli("append", slice_dir, *DEFECT, "--by", " code-reviewer  P3 r1 ")
        assert code == 0 and out.strip() == "B1", err
        b1 = entry_of(slice_dir, "B1")
        assert b1["by"] == BY
        # right after the provenance's author, which it is not matched against
        assert list(b1)[8:10] == ["author", "by"]
        assert b1["author"] == "code-reviewer, P3 r1"
        # without --by, append is what it was, and the key is there all the same
        code, out, err = run_cli("append", slice_dir, *DEFECT)
        assert code == 0 and out.strip() == "B2", err
        b2 = entry_of(slice_dir, "B2")
        assert "by" in b2 and b2["by"] is None
        assert {k: v for k, v in b2.items() if k != "id"} == {
            **{k: v for k, v in b1.items() if k != "id"}, "by": None}
        # the loops' call takes no `by`, and the API's is optional
        e1 = close_out.append_entry(slice_dir, "event", "resumed", "b", consequence="none")
        assert entry_of(slice_dir, e1)["by"] is None
        a1 = close_out.append_entry(slice_dir, "action", "Do X", "b", consequence="none",
                                    proposal="Do it.", by="the driver")
        assert entry_of(slice_dir, a1)["by"] == "the driver"
        # the dispatch line names amend, without its flags and without --overwrite
        line = close_out.dispatch_line("/s/close-out.md")
        assert "`amend <id> --by\n<who>` corrects an entry you appended with that --by" in line
        assert "close_out.py amend" not in line and "overwrite" not in line


def test_amend_replaces_each_field_given_and_leaves_no_note():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        run_cli("append", slice_dir, *DEFECT, "--by", BY)                           # B1
        code, out, err = _amend(slice_dir, "B1", "--headline",
                                "controller: the  roll's status line is wrong",
                                "--body", "-", "--provenance",
                                "read — code-reviewer, P3 r2", by=" code-reviewer P3  r1",
                                stdin="\n  new first line\n\nsecond  \n\n")
        assert code == 0, err
        assert out == "### B1 — controller: the roll's status line is wrong\n"
        b1 = entry_of(slice_dir, "B1")
        assert b1["headline"] == "controller: the roll's status line is wrong"
        assert b1["body"] == ["  new first line", "", "second"]
        assert (b1["evidence"], b1["author"]) == ("read", "code-reviewer, P3 r2")
        assert b1["notes"] == [] and (b1["id"], b1["kind"], b1["by"]) == ("B1", "defect", BY)
        assert "controller: the roll's status line is wrong" in report(slice_dir)
        assert store(slice_dir)["rendered"] == sha256(report(slice_dir))
        # the rest, the same way: the entry is what an append of it would be
        code, out, err = _amend(slice_dir, "B1", "--consequence", "an  operator misreads",
                                "--proposal", "Card it:\n a design.", "--severity", "NIT")
        assert code == 0, err
        assert out == "### B1 — controller: the roll's status line is wrong · nit\n"
        run_cli("append", slice_dir, *with_flags(
            DEFECT, headline="controller: the roll's status line is wrong",
            body="  new first line\n\nsecond", provenance="read — code-reviewer, P3 r2",
            consequence="an operator misreads", proposal="Card it: a design.",
            severity="nit", by=BY))                                                 # B2
        b1, b2 = entry_of(slice_dir, "B1"), entry_of(slice_dir, "B2")
        assert {**b1, "id": "B2"} == b2
        # a defect owes no proposal: an empty one takes it off
        assert _amend(slice_dir, "B1", "--proposal", "")[0] == 0
        assert entry_of(slice_dir, "B1")["proposal"] is None
        # the Python API is the same call
        assert close_out.amend_entry(slice_dir, "B1", BY, headline="h") == "### B1 — h · nit"
        assert entry_of(slice_dir, "B1")["headline"] == "h"


def test_amend_is_refused_once_the_entry_is_committed():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        run_cli("append", slice_dir, *DEFECT, "--by", BY)                           # B1
        # a repository with no commit yet holds nothing
        git(slice_dir.parent.parent, "init", "-q")
        assert _amend(slice_dir, "B1", "--body", "amended")[0] == 0
        commit_store(slice_dir)
        _amend_refused(slice_dir, "B1", ["--body", "again"],
                       "B1 is committed, and a committed entry stays; a note adds to it")
        # an entry appended since is the appender's to amend
        run_cli("append", slice_dir, *DEFECT, "--by", BY)                           # B2
        assert _amend(slice_dir, "B2", "--body", "amended")[0] == 0
        # HEAD holding the entry in any version is committed
        committed = store(slice_dir)
        committed["entries"][1]["body"] = ["what was committed"]
        commit_store(slice_dir, text=json.dumps(committed))
        _amend_refused(slice_dir, "B2", ["--body", "again"], "B2 is committed")
        assert entry_of(slice_dir, "B2")["body"] == ["amended"]


def test_amend_is_refused_to_another_by_and_on_an_entry_appended_without_one():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        run_cli("append", slice_dir, *DEFECT, "--by", BY)                           # B1
        run_cli("append", slice_dir, *DEFECT)                                       # B2
        _amend_refused(slice_dir, "B1", ["--body", "x"],
                       f"B1 was appended by {BY}, not wrap-up: only its appender amends "
                       "an entry", by="wrap-up")
        _amend_refused(slice_dir, "B2", ["--body", "x"],
                       "B2 has no recorded appender (it was appended without --by), so "
                       "nobody amends it; a note adds to it")
        _amend_refused(slice_dir, "B9", ["--body", "x"], "no entry B9")
        # --by is required, and an empty one is none
        assert _amend(slice_dir, "B1", "--body", "x", by=None)[0] == 2
        _amend_refused(slice_dir, "B1", ["--body", "x"],
                       "amend needs --by: who appended the entry", by=" ")
        # nothing to replace, or nothing that changes
        _amend_refused(slice_dir, "B1", [], "amend needs a field to replace: any of "
                       "`append`'s flags but --kind")
        try:
            close_out.amend_entry(slice_dir, "B1", BY, labels={"fix": None})
            raise AssertionError("an amend that gives nothing must raise")
        except ReportError as e:
            assert "amend needs a field to replace" in str(e)
        _amend_refused(slice_dir, "B1", ["--body", "the body", "--trigger",
                                         "ordinary-condition", "--headline",
                                         "controller:  the status line is wrong"],
                       "amend changes nothing on B1")
        # there is no --kind to amend
        assert _amend(slice_dir, "B1", "--kind", "prose")[0] == 2
        # a store written before the key reads as an entry without an appender
        data = store(slice_dir)
        del data["entries"][0]["by"]
        (slice_dir / "close-out.json").write_text(json.dumps(data))
        _amend_refused(slice_dir, "B1", ["--body", "x"], "B1 has no recorded appender")
        assert "### B1 — controller: the status line is wrong" in close_out.show_view(
            slice_dir, ["B1"])


def test_amend_runs_appends_checks_on_the_entry_as_it_would_be():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        run_cli("append", slice_dir, *DEFECT, "--by", BY)                           # B1
        assert _amend(slice_dir, "B1", "--impact", "degraded")[0] == 0
        # the Consequence against the impact, either way round — which relabel skips
        _amend_refused(slice_dir, "B1", ["--consequence", "none"],
                       "--impact degraded over a --consequence that opens with none")
        _amend_refused(slice_dir, "B1", ["--impact", "none", "--signal", "none"],
                       "--impact none over a --consequence that is not none")
        _amend_refused(slice_dir, "B1", ["--signal", "none"],
                       "--signal none with --impact degraded")
        code, _, err = _amend(slice_dir, "B1", "--consequence", "none", "--impact", "none",
                              "--signal", "none")
        assert code == 0, err
        _amend_refused(slice_dir, "B1", ["--signal", "loud"], "--signal loud with --impact none")
        # a field append requires is not emptied
        for flag in ("--headline", "--body", "--consequence"):
            _amend_refused(slice_dir, "B1", [flag, " \n "], f"{flag} needs text")
        # a label of the other family, and a for naming no slice still to run
        _amend_refused(slice_dir, "B1", ["--benefit", "user"],
                       "--benefit: not a label of a defect")
        _amend_refused(slice_dir, "B1", ["--for", "77"], "--for 77: no other slice still to run")
        run_cli("append", slice_dir, *IMPROVEMENT, "--by", BY)                      # I1
        _amend_refused(slice_dir, "I1", ["--trigger", "fault"],
                       "--trigger: not a label of an improvement")
        # an action, a decision and an improvement keep their proposal
        run_cli("append", slice_dir, *ACTION, "--by", BY)                           # A1
        run_cli("append", slice_dir, *DECISION, "--by", BY)                         # D1
        for eid, article in (("A1", "an action"), ("D1", "a decision"),
                             ("I1", "an improvement")):
            for empty in ("", " \n "):
                _amend_refused(slice_dir, eid, ["--proposal", empty],
                               f"Error: {article} needs --proposal: what you would do "
                               "about it and why, in a sentence or two")
        # every refusal in one error
        err = _amend_refused(slice_dir, "A1", ["--proposal", "", "--benefit", "user"],
                             "--benefit: not a label", "an action needs --proposal")
        assert err.count("Error:") == 1


def test_amend_merges_the_labels_over_the_entrys_and_for_none_clears_for():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        run_cli("append", slice_dir, *with_flags(DEFECT, **{"for": "12"}), "--by", BY)
        code, _, err = _amend(slice_dir, "B1", "--fix", "one-edit", "--area", "Plain")
        assert code == 0, err
        b1 = entry_of(slice_dir, "B1")
        assert b1["labels"] == {"trigger": "ordinary-condition", "impact": "broken",
                                "signal": "silent", "fix": "one-edit", "area": "plain",
                                "repo": "KubeCoder", "for": "012"}
        assert list(b1["labels"]) == [k for k in close_out.LABELS if k in b1["labels"]]
        assert b1["notes"] == []
        assert _amend(slice_dir, "B1", "--for", "none")[0] == 0
        assert "for" not in entry_of(slice_dir, "B1")["labels"]
        _amend_refused(slice_dir, "B1", ["--for", "NONE"], "amend changes nothing on B1")
        # a given for is written as the folder's number
        assert _amend(slice_dir, "B1", "--for", "31")[0] == 0
        assert entry_of(slice_dir, "B1")["labels"]["for"] == "031"
        # the CLI documents the clearing value
        _, subs = close_out.build_parser()
        assert "--for none clears it" in " ".join(subs["amend"].format_help().split())


def test_amend_takes_overwrite_and_stops_at_an_edit_without_it():
    _, subs = close_out.build_parser()
    assert "amend" in close_out.WRITING_VERBS
    assert "--overwrite" in subs["amend"].format_help()
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        run_cli("append", slice_dir, *DEFECT, "--by", BY)                           # B1
        _edit(slice_dir, "### B1 — controller: the status line is wrong",
              "### B1 — controller: the status line is wrong, the operator says")
        err = _amend_refused(slice_dir, "B1", ["--body", "amended"],
                             "close-out.md was edited since")
        assert "the operator says" in err
        code, _, err = _amend(slice_dir, "B1", "--body", "amended", "--overwrite")
        assert code == 0, err
        assert entry_of(slice_dir, "B1")["body"] == ["amended"]
        assert "the operator says" not in report(slice_dir)


# -- the wrap-up: marks and worklist ---------------------------------------------

def test_request_card_and_leave_mark_the_entry_and_the_card_is_its_proposal():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        run_cli("append", slice_dir, *DEFECT)                                  # B1
        run_cli("append", slice_dir, *with_flags(DEFECT, fix="one-edit",
                                                 area="plain"))                 # B2
        close_out.propose_entry(slice_dir, "B1", "code-reviewer, P3 r1",
                                "Close it: it needs a fault.", date="2026-09-30")
        code, out, _ = run_cli("request-card", slice_dir, "B1", "--by", "wrap-up",
                               "--text", "reached on every restart;\nneeds a design",
                               "--date", "2026-09-30")
        assert code == 0
        assert out.strip() == ("wrap-up, 2026-09-30 — asks for a card: reached on every "
                               "restart;\nneeds a design")
        b1 = entry_of(slice_dir, "B1")
        assert b1["wrap_up"] == {
            "outcome": "card", "by": "wrap-up", "date": "2026-09-30",
            "text": ["reached on every restart;", "needs a design"]}
        # the card request is the entry's proposal; the one it replaced is a note
        assert b1["proposal"] == "reached on every restart; needs a design"
        assert b1["notes"] == [{"by": "wrap-up", "date": "2026-09-30",
                                "text": ["proposal replaced — was: Close it: it needs a "
                                         "fault."], "history": "proposal"}]
        code, _, _ = run_cli("leave", slice_dir, "B2", "--by", "wrap-up", "--text",
                             "the path is dead code", "--date", "2026-09-30")
        assert code == 0
        assert entry_of(slice_dir, "B2")["proposal"] is None
        close_out.render_report(slice_dir)
        text = report(slice_dir)
        assert _section(text, "Card requests") == (
            "\n## Card requests\n\n### B1 — controller: the status line is wrong\n\n"
            "the body\n\n"
            "**Proposal:** reached on every restart; needs a design\n\n"
            "**Consequence:** an operator reads a wrong status\n\n"
            "**Latest** (wrap-up, 2026-09-30 · 2 notes): asks for a card: reached on every "
            "restart;\nneeds a design\n\n"
            "**Triage:** defect · shows on an ordinary condition · breaks a flow · silent · "
            "fix needs\ndesign · sensitive area · in KubeCoder\n"
            "**Provenance:** witnessed — code-reviewer, P3 r1\n"
            "**Route:** card request — the wrap-up asks for a card\n**Disposition:**\n")
        assert _section(text, "Closed") == (
            "\n## Closed\n\n### B2 — controller: the status line is wrong\n\n"
            "**Consequence:** an operator reads a wrong status\n\n"
            "**Triage:** defect · shows on an ordinary condition · breaks a flow · silent · "
            "fix is one edit ·\nin KubeCoder\n"
            "**Provenance:** witnessed — code-reviewer, P3 r1\n"
            "**Route:** closed — the wrap-up looked and left it\n**Disposition:**\n")
        # the marks are among the notes of the full view
        shown = close_out.show_view(slice_dir, ["B1", "B2"])
        assert ("wrap-up, 2026-09-30 — proposal replaced — was: Close it: it needs a "
                "fault.\n\nwrap-up, 2026-09-30 — asks for a card: reached on every "
                "restart;\nneeds a design\n\n**Proposal:** ") in shown
        assert "wrap-up, 2026-09-30 — looked and left it: the path is dead code" in shown
        # a struck entry takes no mark
        close_out.strike_entry(slice_dir, "B2", "gone")
        code, _, err = run_cli("leave", slice_dir, "B2", "--by", "w", "--text", "t")
        assert code == 2 and "struck" in err


def test_propose_sets_the_proposal_and_keeps_the_one_it_replaces():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        run_cli("append", slice_dir, *DEFECT)                                   # B1
        code, out, err = run_cli("propose", slice_dir, "B1", "--by", "code-reviewer",
                                 "--text", "-", "--date", "2026-10-02",
                                 stdin="Card it:\n  the fix needs a design.\n")
        assert code == 0, err
        assert out.strip() == "**Proposal:** Card it: the fix needs a design."
        b1 = entry_of(slice_dir, "B1")
        assert b1["proposal"] == "Card it: the fix needs a design." and b1["notes"] == []
        line = close_out.propose_entry(slice_dir, "B1", " wrap-up ", "Fix now: one edit.",
                                       date="2026-10-02")
        assert line == "**Proposal:** Fix now: one edit."
        b1 = entry_of(slice_dir, "B1")
        assert b1["proposal"] == "Fix now: one edit."
        assert b1["notes"] == [{"by": "wrap-up", "date": "2026-10-02",
                                "text": ["proposal replaced — was: Card it: the fix needs "
                                         "a design."], "history": "proposal"}]
        # the same proposal again replaces nothing
        close_out.propose_entry(slice_dir, "B1", "wrap-up", "Fix now:  one edit.")
        assert len(entry_of(slice_dir, "B1")["notes"]) == 1
        for eid, by, text, needle in (("B1", "w", " ", "a proposal needs --text"),
                                      ("B1", " ", "t", "a proposal needs --by"),
                                      ("B9", "w", "t", "no entry B9")):
            code, _, err = run_cli("propose", slice_dir, eid, "--by", by, "--text", text)
            assert code == 2 and needle in err, err
        close_out.strike_entry(slice_dir, "B1", "fixed")
        code, _, err = run_cli("propose", slice_dir, "B1", "--by", "w", "--text", "t")
        assert code == 2 and "B1 is struck — a struck entry is settled" in err
        assert entry_of(slice_dir, "B1")["proposal"] == "Fix now: one edit."


def test_a_store_written_before_the_proposal_reads_as_without_one():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        run_cli("append", slice_dir, *ACTION)
        data = store(slice_dir)
        del data["entries"][0]["proposal"]
        (slice_dir / "close-out.json").write_text(json.dumps(data))
        close_out.render_report(slice_dir)
        assert "### A1 — " in report(slice_dir)
        assert "**Proposal:**" not in report(slice_dir)
        assert "**Proposal:**" not in close_out.show_view(slice_dir, ["A1"])
        assert close_out.entry_counts(slice_dir)[close_out.NO_PROPOSAL] == 1
        close_out.propose_entry(slice_dir, "A1", "the operator", "Do it.")
        assert entry_of(slice_dir, "A1")["proposal"] == "Do it."
        assert entry_of(slice_dir, "A1")["notes"] == []


def test_worklist_names_what_waits_and_what_is_asked():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        code, out, _ = run_cli("worklist", slice_dir)
        assert code == 0 and out.strip() == "nothing waits for the wrap-up"
        close_out.append_entry(slice_dir, "Bugs", "unlabelled", "b", consequence="c")  # B1
        run_cli("append", slice_dir, *with_flags(DEFECT, **{"for": "12"}))             # B2
        run_cli("append", slice_dir, *with_flags(DEFECT, fix="one-edit",
                                                 area="plain", severity="minor"))      # B3
        run_cli("append", slice_dir, *with_flags(DEFECT, trigger="unknown"))           # B4
        run_cli("append", slice_dir, *DEFECT)                                          # B5
        run_cli("append", slice_dir, *IMPROVEMENT)                                     # I1
        run_cli("append", slice_dir, *with_flags(DEFECT, trigger="fault"))             # B6
        run_cli("append", slice_dir, *with_flags(DEFECT, trigger="ordinary-condition",
                                                 signal="loud"))                        # B7
        run_cli("append", slice_dir, *with_flags(DEFECT, trigger="fault",
                                                 impact="severe"))                      # B8
        run_cli("append", slice_dir, *with_flags(DEFECT, trigger="fault",
                                                 impact="degraded"))                    # B9
        run_cli("append", slice_dir, *ACTION)                                          # A1
        asked = {e["id"]: a.split(" — ")[0] for e, a in close_out.worklist(slice_dir)}
        assert asked == {"B1": "label", "B2": "fold", "B3": "fix", "B4": "look",
                         "B5": "fix or card", "I1": "improve", "B6": "check",
                         "B7": "check", "B8": "note"}
        items = {e["id"]: a for e, a in close_out.worklist(slice_dir)}
        assert items["B2"] == "fold — fold it into slice 012"
        assert items["B6"] == "check — the trigger the close rests on"
        assert items["B7"] == "check — the signal the close rests on"
        code, out, _ = run_cli("worklist", slice_dir)
        lines = out.splitlines()
        assert lines[0] == "9 entries wait for the wrap-up"
        i = lines.index("B3 · fix")
        assert lines[i + 1] == "    controller: the status line is wrong · minor"
        assert lines[i + 2].startswith("    Triage: defect · shows on an ordinary condition")
        assert lines[i + 3] == "    Consequence: an operator reads a wrong status"
        assert lines[i + 4] == "B4 · look — give the label the author could not"
        # the proposal, where the entry has one, after the Consequence
        i = lines.index("I1 · improve — a small change, within the bar")
        assert lines[i + 3:i + 5] == ["    Consequence: none",
                                      "    Proposal: Drop it now: one caller, one edit."]
        # a mark takes the entry off the list; a struck one is off it too
        close_out.leave_entry(slice_dir, "B6", "wrap-up", "the fault cannot occur")
        close_out.request_card(slice_dir, "B5", "wrap-up", "more than the bar")
        close_out.strike_entry(slice_dir, "B3", "fixed", commit="abc123")
        remaining = [e["id"] for e, _ in close_out.worklist(slice_dir)]
        assert remaining == ["B1", "B2", "B4", "I1", "B7", "B8"]
        # an entry the operator ruled on is theirs: it waits for nobody
        close_out.rule_entry(slice_dir, "B4", words="card it")
        remaining = [e["id"] for e, _ in close_out.worklist(slice_dir)]
        assert remaining == ["B1", "B2", "I1", "B7", "B8"]
        close_out.strike_entry(slice_dir, "B1", "x")
        for eid in ("B2", "I1", "B7", "B8"):
            close_out.leave_entry(slice_dir, eid, "w", "t")
        code, out, _ = run_cli("worklist", slice_dir)
        assert code == 0 and out.strip() == "nothing waits for the wrap-up"


def test_a_for_folds_only_into_a_slice_still_unplanned_and_a_finished_one_drops_out():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp, later=("012_later_slice", "051_planned"))
        root = slice_dir.parent
        plan(root / "051_planned", how="plan")
        close_out.init_report(slice_dir)
        easy = with_flags(DEFECT, fix="one-edit", area="plain")
        run_cli("append", slice_dir, *with_flags(easy, **{"for": "12"}))           # B1
        run_cli("append", slice_dir, *with_flags(easy, **{"for": "51"}))           # B2
        assert [(e["id"], a) for e, a in close_out.worklist(slice_dir)] == [
            ("B1", "fold — fold it into slice 012")]
        counts = close_out.entry_counts(slice_dir)
        assert (counts["to you"], counts["wrap-up"]) == (1, 1)
        assert "**Route:** " + FOR_PLANNED[1] in _section(report(slice_dir),
                                                          "Comes to you")
        assert ("**Route:** the wrap-up — fold into slice 012" in
                _section(report(slice_dir), "For the wrap-up"))
        # 012 runs and is completed: B1 goes where its other labels send it
        (root / "012_later_slice").rename(root / "completed" / "012_later_slice")
        close_out.render_report(slice_dir)
        assert [(e["id"], a) for e, a in close_out.worklist(slice_dir)] == [("B1", "fix")]
        wrap_up = _section(report(slice_dir), "For the wrap-up")
        assert _heads(wrap_up) == ["### B1 — controller: the status line is wrong"]
        assert "**Route:** the wrap-up — fix\n" in wrap_up and "fold" not in wrap_up
        assert FOR_PLANNED[1] in close_out.show_view(slice_dir, ["B2"])


# -- rule, the read-back, close ------------------------------------------------------

def test_rule_records_the_words_and_what_was_done_on_them():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        run_cli("append", slice_dir, *DEFECT)
        run_cli("append", slice_dir, *DEFECT)
        code, out, _ = run_cli("rule", slice_dir, "B1", "--words", "card it, KC",
                               "--date", "2026-09-30")
        assert code == 0 and out.strip() == "B1: card it, KC"
        assert entry_of(slice_dir, "B1")["ruling"] == {"words": "card it, KC",
                                                       "did": None, "date": "2026-09-30"}
        # a second ruling replaces the words on --replace, the old ones in a note
        run_cli("rule", slice_dir, "B1", "--words", "fix now", "--replace",
                "--date", "2026-09-30")
        e = entry_of(slice_dir, "B1")
        assert e["ruling"]["words"] == "fix now"
        assert e["notes"][-1]["text"] == ["ruled earlier: card it, KC"]
        # --did strikes the entry, on the operator's ruling
        code, out, _ = run_cli("rule", slice_dir, "B1", "--did", "fixed in abc123",
                               "--commit", "abc123", "--date", "2026-09-30")
        assert code == 0 and out.strip() == "B1: fix now — fixed in abc123"
        e = entry_of(slice_dir, "B1")
        assert e["strike"] == {"reason": "fixed in abc123", "by": "the operator's ruling",
                               "date": "2026-09-30", "commit": "abc123"}
        # --did without words is refused, unless the words come with it
        code, _, err = run_cli("rule", slice_dir, "B2", "--did", "carded KC-9")
        assert code == 2 and "no ruling" in err and entry_of(slice_dir, "B2")["strike"] is None
        code, _, _ = run_cli("rule", slice_dir, "B2", "--words", "card", "--did",
                             "carded KC-9")
        assert code == 0 and entry_of(slice_dir, "B2")["ruling"]["words"] == "card"
        assert entry_of(slice_dir, "B2")["strike"]["reason"] == "carded KC-9"
        code, _, err = run_cli("rule", slice_dir, "B2")
        assert code == 2 and "--words" in err
        code, _, err = run_cli("rule", slice_dir, "--commit", "x")
        assert code == 2 and "need an entry id" in err


def _write_disposition(slice_dir, eid, words):
    """The operator writes on an entry's Disposition line in close-out.md."""
    text = report(slice_dir)
    start = re.search(rf"^### (~~)?{eid} — .*$", text, re.M).start()
    nxt = re.search(r"^(### |## )", text[start + 4:], re.M)
    end = start + 4 + nxt.start() if nxt else len(text)
    block = text[start:end]
    i = block.rindex("**Disposition:**")
    j = block.find("\n\n", i)
    j = len(block) if j == -1 else j
    block = block[:i] + "**Disposition:** " + words + block[j:]
    (slice_dir / "close-out.md").write_text(text[:start] + block + text[end:])


def test_the_disposition_lines_are_read_back_into_the_store():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        run_cli("append", slice_dir, *ACTION)                                    # A1
        for _ in range(2):
            run_cli("append", slice_dir, *DEFECT)                                # B1, B2
        run_cli("append", slice_dir, *with_flags(DEFECT, trigger="fault"))       # B3
        close_out.render_report(slice_dir)
        code, out, _ = run_cli("rule", slice_dir)
        assert code == 0 and out.strip() == "nothing to take from the Disposition lines"
        # one line; several lines; under an ask, under a closed entry
        _write_disposition(slice_dir, "A1", "done")
        _write_disposition(slice_dir, "B1", "card KC")
        _write_disposition(slice_dir, "B2", "close —\nit is fixed upstream")
        _write_disposition(slice_dir, "B3", "agreed")
        code, out, _ = run_cli("rule", slice_dir)
        assert code == 0
        assert out.splitlines() == ["A1: done", "B1: card KC",
                                    "B2: close — it is fixed upstream", "B3: agreed"]
        assert entry_of(slice_dir, "B2")["ruling"]["words"] == \
            "close —\nit is fixed upstream"
        assert entry_of(slice_dir, "B3")["ruling"]["words"] == "agreed"
        # a second read-back takes nothing: the file says what the store does
        code, out, _ = run_cli("rule", slice_dir)
        assert out.strip() == "nothing to take from the Disposition lines"
        close_out.render_report(slice_dir)
        assert "**Disposition:** close —\nit is fixed upstream\n" in report(slice_dir)


def test_a_report_rendered_with_folds_is_read_back_before_its_first_re_render():
    """A close-out.md as 0.9.57–0.9.69 rendered it — bodies folded in
    `<details>`, the record folded whole with its Disposition line inside —
    still gives up what the operator wrote, and the next render drops the
    folds."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        for _ in range(2):
            run_cli("append", slice_dir, *with_flags(DEFECT, fix="one-edit",
                                                     area="plain"))              # B1, B2
        close_out.rule_entry(slice_dir, "B2", words="fold into 012", date="2026-09-29")
        close_out.rule_entry(slice_dir, "B2", did="folded", date="2026-09-29")
        # a store of then, written before it kept the hash of its render
        data = store(slice_dir)
        del data["rendered"]
        close_out._save(slice_dir, data)
        triage = ("**Triage:** defect · shows on an ordinary condition · breaks a flow · "
                  "silent · fix is one edit · in\nKubeCoder")
        (slice_dir / "close-out.md").write_text(
            "# Close-out — slice 007 argocd_tools_presync_hook\n\n"
            "<!-- Generated by `close_out.py render` from close-out.json, the record. "
            "The `Disposition:`\n     lines are yours to write; everything else is "
            "overwritten by the next render. -->\n\nRun: <not yet stamped>\n\n"
            "## For the wrap-up\n\n"
            "### B1 — controller: the status line is wrong\n\n"
            "<details><summary>body</summary>\n\nthe body\n\n</details>\n\n"
            "**Consequence:** an operator reads a wrong status\n\n"
            f"{triage}\n**Provenance:** witnessed — code-reviewer, P3 r1\n"
            "**Route:** the wrap-up — fix\n**Disposition:** card KC,\nin KubeCoder\n\n"
            "## Record\n\n"
            "### ~~B2 — controller: the status line is wrong~~ — folded; struck by the "
            "operator's ruling\n\n"
            "<details><summary>struck — kept for the record</summary>\n\nthe body\n\n"
            "**Consequence:** an operator reads a wrong status\n\n"
            f"{triage}\n**Provenance:** witnessed — code-reviewer, P3 r1\n"
            "**Disposition:** fold into 031 — folded\n\n</details>\n")
        close_out.render_report(slice_dir)
        assert entry_of(slice_dir, "B1")["ruling"]["words"] == "card KC,\nin KubeCoder"
        b2 = entry_of(slice_dir, "B2")
        assert b2["ruling"]["words"] == "fold into 031" and b2["ruling"]["did"] == "folded"
        assert b2["notes"][-1]["text"] == ["ruled earlier: fold into 012"]
        text = report(slice_dir)
        assert "<details>" not in text and "</details>" not in text
        assert "**Disposition:** card KC,\nin KubeCoder\n" in text
        assert close_out.read_back(slice_dir) == []


def test_render_keeps_what_the_operator_wrote():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        run_cli("append", slice_dir, *DEFECT)
        close_out.render_report(slice_dir)
        _write_disposition(slice_dir, "B1", "card it")
        # another writer appends meanwhile; the render keeps both
        run_cli("append", slice_dir, *IMPROVEMENT)
        close_out.render_report(slice_dir)
        assert entry_of(slice_dir, "B1")["ruling"]["words"] == "card it"
        assert "**Disposition:** card it\n" in report(slice_dir)
        assert "### I1 — " in report(slice_dir)
        # a blank line is nothing to take: the words stay
        _write_disposition(slice_dir, "B1", "")
        close_out.render_report(slice_dir)
        assert entry_of(slice_dir, "B1")["ruling"]["words"] == "card it"


def test_a_ruling_rule_replaces_stands_through_the_next_render():
    """AIWF-45: `rule` left the page on the old words, and the next render
    read them back as the ruling."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        run_cli("append", slice_dir, *DEFECT)
        close_out.rule_entry(slice_dir, "B1", words="A", date="2026-10-09")
        close_out.render_report(slice_dir)
        code, out, _ = run_cli("rule", slice_dir, "B1", "--words", "B", "--replace",
                               "--date", "2026-10-09")
        assert code == 0 and out.strip() == "B1: B"
        assert "**Disposition:** B\n" in report(slice_dir)
        close_out.render_report(slice_dir)
        b1 = entry_of(slice_dir, "B1")
        assert b1["ruling"]["words"] == "B"
        assert b1["notes"] == [{"by": "the operator", "date": "2026-10-09",
                                "text": ["ruled earlier: A"], "history": "ruling"}]
        assert "**Disposition:** B\n" in report(slice_dir)


def test_every_write_leaves_the_report_as_render_writes_it():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)

        def as_rendered():
            text = report(slice_dir)
            close_out.render_report(slice_dir)
            assert report(slice_dir) == text
            return text

        run_cli("append", slice_dir, *DEFECT)                                    # B1
        assert "### B1 — controller: the status line is wrong\n" in as_rendered()
        run_cli("append", slice_dir, *DEFECT)                                    # B2
        run_cli("append", slice_dir, *IMPROVEMENT)                               # I1
        assert "### I1 — drop the duplicate helper\n" in as_rendered()
        run_cli("note", slice_dir, "B1", "--by", "op", "--text", "the premise moved",
                "--date", "2026-10-09")
        assert "**Latest** (op, 2026-10-09): the premise moved\n" in as_rendered()
        run_cli("propose", slice_dir, "I1", "--by", "w", "--text", "Keep both.")
        assert "**Proposal:** Keep both.\n" in as_rendered()
        run_cli("relabel", slice_dir, "B1", "--by", "w", "--note", "one call site",
                "--fix", "one-edit", "--date", "2026-10-09")
        assert "fix is one edit" in " ".join(as_rendered().split())
        run_cli("strike", slice_dir, "B2", "--reason", "dup")
        assert "### ~~B2 — controller: the status line is wrong~~ — dup\n" in as_rendered()


def test_a_disposition_the_operator_wrote_is_taken_by_the_next_write_of_any_verb():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        run_cli("append", slice_dir, *DEFECT)                                    # B1
        run_cli("append", slice_dir, *IMPROVEMENT)                               # I1
        _write_disposition(slice_dir, "B1", "card it")
        code, _, err = run_cli("note", slice_dir, "I1", "--by", "op", "--text", "seen")
        assert code == 0, err
        assert entry_of(slice_dir, "B1")["ruling"]["words"] == "card it"
        assert "**Disposition:** card it\n" in report(slice_dir)
        code, out, _ = run_cli("rule", slice_dir)
        assert out.strip() == "nothing to take from the Disposition lines"


def test_a_write_that_fails_leaves_the_store_and_the_report_as_they_were():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        run_cli("append", slice_dir, *DEFECT)                                    # B1
        _write_disposition(slice_dir, "B1", "card it")
        before = (store(slice_dir), report(slice_dir))
        code, _, err = run_cli("note", slice_dir, "B9", "--by", "op", "--text", "t")
        assert code == 2 and "no entry B9" in err
        assert (store(slice_dir), report(slice_dir)) == before
        # the words are still on the page for the next write to take
        close_out.render_report(slice_dir)
        assert entry_of(slice_dir, "B1")["ruling"]["words"] == "card it"


def _edit(slice_dir, old, new):
    """The operator edits close-out.md by hand: `old` becomes `new`."""
    text = report(slice_dir)
    assert old in text, old
    (slice_dir / "close-out.md").write_text(text.replace(old, new, 1))


def _files(slice_dir):
    return ((slice_dir / "close-out.json").read_bytes(),
            (slice_dir / "close-out.md").read_bytes())


def test_the_store_keeps_the_hash_of_the_report_it_last_wrote():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        assert store(slice_dir)["rendered"] == sha256(report(slice_dir))
        # every write moves it on with the report
        run_cli("append", slice_dir, *DEFECT)                                    # B1
        assert store(slice_dir)["rendered"] == sha256(report(slice_dir))
        run_cli("note", slice_dir, "B1", "--by", "op", "--text", "seen")
        assert store(slice_dir)["rendered"] == sha256(report(slice_dir))
        run_cli("strike", slice_dir, "B1", "--reason", "dup")
        assert store(slice_dir)["rendered"] == sha256(report(slice_dir))
        # a render that writes the same bytes leaves the store as it was
        before = _files(slice_dir)
        close_out.render_report(slice_dir)
        assert _files(slice_dir) == before


def test_a_store_without_the_hash_is_clean_once_and_gets_it():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        run_cli("append", slice_dir, *DEFECT)                                    # B1
        data = store(slice_dir)
        del data["rendered"]
        close_out._save(slice_dir, data)
        _edit(slice_dir, "the body\n", "the body\nan aside\n")
        code, _, err = run_cli("note", slice_dir, "B1", "--by", "op", "--text", "seen")
        assert code == 0, err
        assert "an aside" not in report(slice_dir)
        assert store(slice_dir)["rendered"] == sha256(report(slice_dir))
        # from here on it is compared
        _edit(slice_dir, "the body\n", "the body\nan aside\n")
        code, _, err = run_cli("note", slice_dir, "B1", "--by", "op", "--text", "again")
        assert code == 2 and "> an aside" in err


def test_an_edit_the_read_back_takes_stops_no_write():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        run_cli("append", slice_dir, *DEFECT)                                    # B1
        run_cli("append", slice_dir, *IMPROVEMENT)                               # I1
        _write_disposition(slice_dir, "B1", "card it,\nin KubeCoder")
        assert close_out.edited_report(slice_dir) is None
        code, _, err = run_cli("note", slice_dir, "I1", "--by", "op", "--text", "seen")
        assert code == 0, err
        assert entry_of(slice_dir, "B1")["ruling"]["words"] == "card it,\nin KubeCoder"
        assert store(slice_dir)["rendered"] == sha256(report(slice_dir))
        # blank lines are nothing either
        _edit(slice_dir, "## ", "\n\n## ")
        code, _, err = run_cli("note", slice_dir, "I1", "--by", "op", "--text", "more")
        assert code == 0, err


def test_an_edit_a_render_would_drop_refuses_the_write_until_overwritten():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        run_cli("append", slice_dir, *DEFECT)                                    # B1
        run_cli("append", slice_dir, *IMPROVEMENT)                               # I1
        _edit(slice_dir, "the body\n", "the body\nthe operator's aside\n")
        _edit(slice_dir, "### I1 — drop the duplicate helper",
              "### I1 — drop the duplicated helper")
        _write_disposition(slice_dir, "B1", "keep it locked")
        before = _files(slice_dir)
        try:
            close_out.add_note(slice_dir, "I1", "op", "seen")
            raise AssertionError("the write went through")
        except close_out.ReportEdited as e:
            assert e.taken == [("B1", "keep it locked")]
            assert e.dropped == ["the operator's aside",
                                 "### I1 — drop the duplicated helper"]
            assert str(e) == (
                "close-out.md was edited since close_out.py last wrote it, and this "
                "write would drop what was edited — nothing was written.\n"
                "The Disposition lines it takes into the store:\n"
                "  B1: keep it locked\n"
                "The lines a re-render drops — an edit, or a line an older plugin "
                "rendered otherwise:\n"
                "  > the operator's aside\n"
                "  > ### I1 — drop the duplicated helper\n" + close_out.EDITED_TAIL)
        assert _files(slice_dir) == before
        # the CLI says the same, exit 2
        code, _, err = run_cli("note", slice_dir, "I1", "--by", "op", "--text", "seen")
        assert code == 2 and err.startswith("Error: close-out.md was edited since")
        assert "  > the operator's aside\n" in err
        assert _files(slice_dir) == before
        # with the permission it goes through: the Disposition is taken, the rest dropped
        with close_out.overwriting():
            with close_out.overwriting():       # re-entrant
                pass
            close_out.add_note(slice_dir, "I1", "op", "seen")
        assert "the operator's aside" not in report(slice_dir)
        assert "### I1 — drop the duplicate helper\n" in report(slice_dir)
        assert entry_of(slice_dir, "B1")["ruling"]["words"] == "keep it locked"
        assert store(slice_dir)["rendered"] == sha256(report(slice_dir))
        # and the permission ends with the block
        _edit(slice_dir, "the body\n", "the body\nonce more\n")
        code, _, err = run_cli("note", slice_dir, "I1", "--by", "op", "--text", "x")
        assert code == 2
        code, _, err = run_cli("note", slice_dir, "I1", "--by", "op", "--text", "x",
                               "--overwrite")
        assert code == 0, err
        assert "once more" not in report(slice_dir)


def test_a_write_with_nothing_to_render_checks_nothing():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        run_cli("append", slice_dir, *DEFECT)                                    # B1
        close_out.rule_entry(slice_dir, "B1", words="card it")
        _edit(slice_dir, "the body\n", "the body\nan aside\n")
        before = _files(slice_dir)
        # the same words again change nothing, so nothing is rendered
        assert close_out.rule_entry(slice_dir, "B1", words="card it") == "B1: card it"
        assert _files(slice_dir) == before


def test_the_run_header_moving_on_is_not_an_edit():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        state = dict(STATE, run_phase="phases", doc_phase=None, test_rounds=0)
        (slice_dir / "state.json").write_text(json.dumps(state))
        close_out.init_report(slice_dir)
        run_cli("append", slice_dir, *DEFECT)                                    # B1
        run_cli("append", slice_dir, *IMPROVEMENT)                               # I1
        old_header = report(slice_dir)
        state.update(updated_at="2026-08-15T09:12:00+02:00", test_rounds=2,
                     known_phases=[*STATE["known_phases"], "12", "13"],
                     appended_phases=[*STATE["appended_phases"], "12", "13"])
        (slice_dir / "state.json").write_text(json.dumps(state))
        _write_disposition(slice_dir, "B1", "card it")
        assert close_out.edited_report(slice_dir) is None
        code, _, err = run_cli("note", slice_dir, "I1", "--by", "op", "--text", "seen")
        assert code == 0, err
        assert report(slice_dir).split("\n## ")[0] != old_header.split("\n## ")[0]
        assert "2 test rounds" in " ".join(report(slice_dir).split())


def test_what_the_write_itself_removes_is_not_the_edit():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        run_cli("append", slice_dir, *with_flags(DEFECT, body="the first body",
                                                 consequence="a first consequence"))
        run_cli("append", slice_dir, *with_flags(DEFECT, body="the second body"))
        _edit(slice_dir, "the second body\n", "the second body\nthe operator's aside\n")
        try:
            close_out.strike_entry(slice_dir, "B1", "dup")
            raise AssertionError("the strike went through")
        except close_out.ReportEdited as e:
            # the strike takes B1's ask off the page; only the aside is listed
            assert e.dropped == ["the operator's aside"] and e.taken == []
            assert "The Disposition lines it takes" not in str(e)
        assert entry_of(slice_dir, "B1")["strike"] is None


def test_edited_report_is_the_check_without_the_write():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        assert close_out.edited_report(slice_dir) is None                        # no store
        close_out.init_report(slice_dir)
        run_cli("append", slice_dir, *DEFECT)                                    # B1
        assert close_out.edited_report(slice_dir) is None
        _write_disposition(slice_dir, "B1", "card it")
        _edit(slice_dir, "the body\n", "the body\nan aside\n")
        before = _files(slice_dir)
        found = close_out.edited_report(slice_dir)
        assert isinstance(found, close_out.ReportEdited)
        assert found.dropped == ["an aside"] and found.taken == [("B1", "card it")]
        assert _files(slice_dir) == before
        (slice_dir / "close-out.md").unlink()
        assert close_out.edited_report(slice_dir) is None                        # missing


def test_overwrite_is_on_every_writing_verb_and_never_in_the_dispatch():
    _, subs = close_out.build_parser()
    for name, sub in subs.items():
        flags = {s for a in sub._actions for s in a.option_strings}
        assert ("--overwrite" in flags) == (name in close_out.WRITING_VERBS), name
    assert "--overwrite" in subs["note"].format_help()
    assert "overwrite" not in close_out.dispatch_line("/s/close-out.md")
    assert "overwrite" not in close_out.verb_usage(*close_out.WRITING_VERBS)
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        code, _, err = run_cli("append", slice_dir, *DEFECT, "--overwrite")
        assert code == 0, err
        for argv in (["note", "B1", "--by", "op", "--text", "t"],
                     ["unnote", "B1", "--by", "op"],
                     ["propose", "B1", "--by", "op", "--text", "t"],
                     ["relabel", "B1", "--by", "op", "--note", "n", "--fix", "one-edit"],
                     ["rule", "B1", "--words", "card it"],
                     ["rule"],
                     ["render"],
                     ["strike", "B1", "--reason", "r", "--by", "op"],
                     ["unstrike", "B1", "--by", "op"],
                     ["strike", "B1", "--reason", "r"]):
            code, _, err = run_cli(argv[0], slice_dir, *argv[1:], "--overwrite")
            assert code == 0, (argv, err)


def test_rule_never_replaces_words_the_entry_holds_unasked():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        for _ in range(4):
            run_cli("append", slice_dir, *DECISION)                              # D1–D4
        close_out.rule_entry(slice_dir, "D1", words="keep it locked", date="2026-10-10")
        before = _files(slice_dir)
        code, _, err = run_cli("rule", slice_dir, "D1", "--words", "The rest is agreed")
        assert code == 2
        assert ("D1 already holds the operator's words: \"keep it locked\". --append adds "
                "these after them") in err
        assert _files(slice_dir) == before
        # the same words, whitespace aside: nothing to do
        code, out, _ = run_cli("rule", slice_dir, "D1", "--words", " keep  it locked ")
        assert code == 0 and out.strip() == "D1: keep it locked"
        assert _files(slice_dir) == before
        # --append joins them, no note
        code, out, _ = run_cli("rule", slice_dir, "D1", "--words", "and say why",
                               "--append", "--date", "2026-10-11")
        assert code == 0 and out.strip() == "D1: keep it locked; and say why"
        d1 = entry_of(slice_dir, "D1")
        assert d1["ruling"] == {"words": "keep it locked; and say why", "did": None,
                                "date": "2026-10-11"}
        assert d1["notes"] == []
        # --replace puts them in place, the old in a note
        close_out.rule_entry(slice_dir, "D2", words="A", date="2026-10-10")
        code, out, _ = run_cli("rule", slice_dir, "D2", "--words", "B", "--replace",
                               "--date", "2026-10-11")
        assert code == 0 and out.strip() == "D2: B"
        assert entry_of(slice_dir, "D2")["notes"] == [
            {"by": "the operator", "date": "2026-10-11", "text": ["ruled earlier: A"],
             "history": "ruling"}]
        # on an entry without words either is plain --words
        for eid, mode in (("D3", "--append"), ("D4", "--replace")):
            code, out, _ = run_cli("rule", slice_dir, eid, "--words", "agreed", mode)
            assert code == 0 and out.strip() == f"{eid}: agreed"
            assert entry_of(slice_dir, eid)["ruling"]["words"] == "agreed"
            assert entry_of(slice_dir, eid)["notes"] == []
        # usage: either needs --words and an id; not both at once
        code, _, err = run_cli("rule", slice_dir, "D1", "--append")
        assert code == 2 and "--append needs --words" in err
        code, _, err = run_cli("rule", slice_dir, "D1", "--did", "done", "--replace")
        assert code == 2 and "--replace needs --words" in err
        code, _, err = run_cli("rule", slice_dir, "--append")
        assert code == 2 and "need an entry id" in err
        code, _, _ = run_cli("rule", slice_dir, "D1", "--words", "x", "--append",
                             "--replace")
        assert code == 2
        # the operator's own Disposition line still replaces, the old in a note
        _write_disposition(slice_dir, "D3", "no, card it")
        close_out.render_report(slice_dir)
        d3 = entry_of(slice_dir, "D3")
        assert d3["ruling"]["words"] == "no, card it"
        assert d3["notes"][-1]["text"] == ["ruled earlier: agreed"]


def test_close_leaves_a_ruling_nobody_executed_live_and_the_report_open():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        for _ in range(2):
            run_cli("append", slice_dir, *DEFECT)
        close_out.rule_entry(slice_dir, "B2", words="defer", date="2026-09-30")
        code, out, _ = run_cli("close", slice_dir, "--words", "close the rest",
                               "--date", "2026-10-01")
        assert code == 0
        assert out.strip() == ("1 entry closed; the report stays open over B2, "
                               "ruled and not executed")
        data = store(slice_dir)
        assert data["closed"] is None
        b1, b2 = data["entries"]
        assert b1["strike"]["reason"] == "closed with the report, 2026-10-01"
        assert b2["strike"] is None and b2["ruling"]["words"] == "defer"
        # executed, the entry is settled and the report closes
        close_out.rule_entry(slice_dir, "B2", did="carded as KC-1", date="2026-10-02")
        code, out, _ = run_cli("close", slice_dir, "--words", "done",
                               "--date", "2026-10-02")
        assert code == 0 and out.strip() == "closed, 0 entries with it"
        assert store(slice_dir)["closed"] == {"date": "2026-10-02", "words": "done"}


def test_close_rules_and_strikes_every_live_entry_once():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        for _ in range(3):
            run_cli("append", slice_dir, *DEFECT)
        close_out.strike_entry(slice_dir, "B3", "dup", date="2026-09-29")
        code, out, _ = run_cli("close", slice_dir, "--words", "done with it",
                               "--date", "2026-10-01")
        assert code == 0 and out.strip() == "closed, 2 entries with it"
        data = store(slice_dir)
        assert data["closed"] == {"date": "2026-10-01", "words": "done with it"}
        b1, b2, b3 = data["entries"]
        for e in (b1, b2):
            assert e["ruling"] == {"words": "done with it", "did": None,
                                   "date": "2026-10-01"}
            assert e["strike"]["reason"] == "closed with the report, 2026-10-01"
        assert b3["strike"]["reason"] == "dup"
        code, _, err = run_cli("close", slice_dir, "--words", "again")
        assert code == 2 and "closed on 2026-10-01" in err
        close_out.render_report(slice_dir)
        text = report(slice_dir)
        assert "\nClosed: 2026-10-01 — done with it\n" in text
        assert text.index("Run: ") < text.index("Closed: ") < text.index("## Record")
        counts = close_out.entry_counts(slice_dir)
        assert close_out.counts_line(counts).startswith(
            "to you 0 · card requests 0 · wrap-up 0 · unlabelled 0 · closed 0 · record 0")


# -- settle: a criterion owed after an operator's action ------------------------------

DEPLOY = "the operator runs the deploy against prd"


def _criterion(vid, owed_after=None, verdict=None, evidence=(), desc="d"):
    item = {"id": vid, "area": "deploy", "description": desc}
    if owed_after is not None:
        item["owed_after"] = owed_after
    item.update(verdict=verdict, rationale="", evidence=list(evidence))
    return item


def _owed_slice(tmp, items, store=True, **dump):
    slice_dir = make_slice(tmp)
    (slice_dir / "verification.json").write_text(
        json.dumps({"items": items}, **{"indent": 2, **dump}) + "\n")
    if store:
        close_out.init_report(slice_dir)
    return slice_dir


def _verification(slice_dir):
    return {i["id"]: i for i in
            json.loads((slice_dir / "verification.json").read_text())["items"]}


def _seed_owed(slice_dir, vid, after):
    """The action plan_loop.py seeds for a criterion owed after anything
    but a push hold (`_owed_entries`)."""
    return close_out.append_entry(
        slice_dir, "Outstanding actions", f"Settle {vid} after {after}",
        f"{vid} — d\n\n`verification.json` marks {vid} owed after: {after}. The run "
        "cannot take that action; settle the criterion once it has happened.",
        consequence=f"{vid} stays unproven until then; the test phase does not settle it.",
        provenance="read — `verification.json`'s `owed_after`, seeded by the plan loop",
        proposal=f"When that has happened, say so: the session settles {vid} in "
                 "verification.json.")


def _seed_hold(slice_dir, rows):
    """The action plan_loop.py seeds for a `## Push holds` repo with
    criteria owed after the push."""
    return close_out.append_entry(
        slice_dir, "Outstanding actions", "Push HelmCharts by hand when its hold lifts",
        "`plan.md`'s `## Push holds` section holds `../HelmCharts`: review first\n\n"
        "Criteria owed after that push — the run cannot prove them, so they stay open "
        "until the push lands and are settled after it:\n\n" + "\n".join(rows),
        consequence="until you push it, nothing HelmCharts deploys carries the slice.",
        provenance="read — `plan.md`'s `## Push holds`, seeded by the plan loop",
        proposal="Push it when the hold lifts, then say so.")


def test_settle_writes_the_verdict_and_strikes_the_action_that_waited_on_it():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = _owed_slice(tmp, [
            _criterion("V16", verdict="pass", evidence=["suite green"]),
            _criterion("V17", DEPLOY, "owed", ["helm template renders"])])
        _seed_owed(slice_dir, "V17", DEPLOY)                                     # A1
        _seed_owed(slice_dir, "V171", DEPLOY)                                    # A2
        before = _verification(slice_dir)["V16"]
        code, out, err = run_cli("settle", slice_dir / "close-out.md", "V17",
                                 "--verdict", "pass", "--evidence",
                                 "the operator: deployed, the pod is green",
                                 "--by", "close-out session")
        assert code == 0, err
        today = close_out._today()
        assert out.splitlines() == [
            "V17 settled pass in verification.json",
            f"### ~~A1 — Settle V17 after {DEPLOY}~~ — settled V17 pass in "
            "verification.json; struck by close-out session"]
        v = _verification(slice_dir)
        assert v["V17"] == {
            "id": "V17", "area": "deploy", "description": "d", "owed_after": DEPLOY,
            "verdict": "pass", "rationale": f"Settled pass after {DEPLOY}, {today}.",
            "evidence": ["helm template renders",
                         "the operator: deployed, the pod is green"]}
        assert v["V16"] == before
        a1, a2 = store(slice_dir)["entries"]
        assert a1["strike"] == {"reason": "settled V17 pass in verification.json",
                                "by": "close-out session", "date": today, "commit": None}
        assert a2["strike"] is None                                    # V171 is not V17
        assert "~~A1 — Settle V17 after" in report(slice_dir)


def test_settle_replaces_the_rationale_adds_the_evidence_and_needs_no_store():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = _owed_slice(tmp, [_criterion("V03", "../HelmCharts")], store=False)
        item = _verification(slice_dir)["V03"]
        item.update(rationale="offline half proven", evidence="helm lint clean")
        (slice_dir / "verification.json").write_text(
            json.dumps({"items": [item]}, indent=2) + "\n")
        code, out, err = run_cli("settle", slice_dir, "V03", "--verdict", "fail",
                                 "--evidence", "the rollout stalled",
                                 "--evidence", "-", "--rationale",
                                 "The pod never went ready after the push.",
                                 stdin="kubectl rollout status: timed out\n")
        assert code == 0, err
        assert out.splitlines() == ["V03 settled fail in verification.json"]
        assert _verification(slice_dir)["V03"] == dict(
            item, verdict="fail", rationale="The pod never went ready after the push.",
            evidence=["helm lint clean", "the rollout stalled",
                      "kubectl rollout status: timed out"])
        assert not (slice_dir / "close-out.json").exists()
        assert not (slice_dir / "close-out.md").exists()


def test_settle_refuses_what_is_not_owed_and_writes_nothing():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = _owed_slice(tmp, [
            _criterion("V01", verdict="owed"),
            _criterion("V02", DEPLOY, "pass"),
            _criterion("V03", DEPLOY, "proven offline"),
            _criterion("V04", "  "),
            _criterion("V05", DEPLOY, "owed")])
        _seed_owed(slice_dir, "V02", DEPLOY)                                     # A1
        verification = (slice_dir / "verification.json").read_bytes()
        files = _files(slice_dir)
        ev = ["--verdict", "pass", "--evidence", "seen"]
        for argv, needle in (
                (["V99", *ev], "no criterion V99 in"),
                (["V01", *ev], "V01 has no owed_after"),
                (["V04", *ev], "V04 has no owed_after"),
                (["V02", *ev], "V02's verdict is 'pass' already"),
                (["V03", *ev], "V03's verdict is 'proven offline' already"),
                (["V05", "--verdict", "pass", "--evidence", " "], "settle needs --evidence"),
                (["V05", *ev, "--rationale", ""], "--rationale is empty")):
            code, _, err = run_cli("settle", slice_dir, *argv)
            assert code == 2 and needle in err, (argv, err)
            assert (slice_dir / "verification.json").read_bytes() == verification
            assert _files(slice_dir) == files
        # argparse's own: a verdict other than pass or fail, no --evidence
        assert run_cli("settle", slice_dir, "V05", "--verdict", "owed",
                       "--evidence", "x")[0] == 2
        assert run_cli("settle", slice_dir, "V05", "--verdict", "pass")[0] == 2
        # a verification.json that is not one
        for text, needle in (("[]", "not an object with an `items` list"),
                             ('{"items": {}}', "not an object with an `items` list"),
                             ("{", "not valid JSON")):
            (slice_dir / "verification.json").write_text(text)
            code, _, err = run_cli("settle", slice_dir, "V05", *ev)
            assert code == 2 and needle in err, (text, err)
            assert (slice_dir / "verification.json").read_text() == text
        (slice_dir / "verification.json").unlink()
        code, _, err = run_cli("settle", slice_dir, "V05", *ev)
        assert code == 2 and "verification.json does not exist" in err
        assert _files(slice_dir) == files


def test_settle_writes_verification_json_in_the_files_own_escaping():
    items = [_criterion("V01", desc="the chart — rendered"),
             _criterion("V02", DEPLOY, "owed", desc="the pod — ready"),
             _criterion("V03", desc="the café’s sign")]
    with tempfile.TemporaryDirectory() as tmp:
        for dump, newline in (({"indent": 2, "ensure_ascii": True}, ""),
                              ({"indent": 4, "ensure_ascii": False}, "\n")):
            slice_dir = Path(tmp) / f"{dump['indent']}" / "slice"
            slice_dir.mkdir(parents=True)
            raw = json.dumps({"items": items}, **dump) + newline
            (slice_dir / "verification.json").write_text(raw)
            code, _, err = run_cli("settle", slice_dir, "V02", "--verdict", "pass",
                                   "--evidence", "deployed — green", "--rationale", "r")
            assert code == 0, err
            new = (slice_dir / "verification.json").read_text()
            expected = [dict(i) for i in items]
            expected[1].update(verdict="pass", rationale="r", evidence=["deployed — green"])
            assert new == json.dumps({"items": expected}, **dump) + newline, dump
            # only V02's verdict, rationale and evidence lines differ
            old_lines, new_lines = raw.splitlines(), new.splitlines()
            changed = [line for line in difflib.ndiff(old_lines, new_lines)
                       if line[:2] in ("- ", "+ ")]
            assert all(re.search(r'"verdict"|"rationale"|"evidence"|deployed|^[-+]\s+\]',
                                 line) for line in changed), changed
            assert ("\\u2014" in new) == dump["ensure_ascii"]
            assert ("—" in new) != dump["ensure_ascii"]
        # a file no setting reproduces takes the nearest: here, indent 4 and the
        # literal dash, the one hand-spaced line normalised with the change
        slice_dir = Path(tmp) / "odd" / "slice"
        slice_dir.mkdir(parents=True)
        raw = json.dumps({"items": items}, indent=4, ensure_ascii=False) + "\n"
        raw = raw.replace('"area": "deploy"', '"area":  "deploy"', 1)
        (slice_dir / "verification.json").write_text(raw)
        code, _, err = run_cli("settle", slice_dir, "V02", "--verdict", "pass",
                               "--evidence", "e", "--rationale", "r")
        assert code == 0, err
        expected = [dict(i) for i in items]
        expected[1].update(verdict="pass", rationale="r", evidence=["e"])
        assert (slice_dir / "verification.json").read_text() == json.dumps(
            {"items": expected}, indent=4, ensure_ascii=False) + "\n"


def test_settling_a_push_holds_criteria_notes_its_action_until_the_last_is_settled():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = _owed_slice(tmp, [
            _criterion("V01", "../HelmCharts", "owed"),
            _criterion("V02", "../HelmCharts", "owed"),
            _criterion("V03", "../HelmCharts", "owed")])
        _seed_hold(slice_dir, ["- V01 — the chart deploys", "- V02"])           # A1
        _seed_hold(slice_dir, ["- V03 — the other chart"])                       # A2
        _seed_hold(slice_dir, ["- V01 — the chart deploys"])                     # A3
        close_out.strike_entry(slice_dir, "A3", "superseded by A1")
        today = close_out._today()
        code, out, err = run_cli("settle", slice_dir, "V01", "--verdict", "pass",
                                 "--evidence", "the operator pushed; the chart is live")
        assert code == 0, err
        note = "V01 settled pass in verification.json; V02 still owed."
        assert out.splitlines() == ["V01 settled pass in verification.json",
                                    f"A1 noted: settle, {today} — {note}"]
        a1, a2, a3 = store(slice_dir)["entries"]
        assert a1["strike"] is None
        assert a1["notes"] == [{"by": "settle", "date": today, "text": [note]}]
        assert a2["notes"] == [] and a2["strike"] is None
        assert a3["notes"] == [] and a3["strike"]["reason"] == "superseded by A1"
        code, out, err = run_cli("settle", slice_dir, "V02", "--verdict", "fail",
                                 "--evidence", "the second job failed",
                                 "--by", "close-out session")
        assert code == 0, err
        assert out.splitlines() == [
            "V02 settled fail in verification.json",
            "### ~~A1 — Push HelmCharts by hand when its hold lifts~~ — settled V01 "
            "pass, V02 fail in verification.json; struck by close-out session"]
        a1, a2, _ = store(slice_dir)["entries"]
        assert a1["strike"]["reason"] == "settled V01 pass, V02 fail in verification.json"
        assert a1["strike"]["by"] == "close-out session" and len(a1["notes"]) == 1
        assert a2["strike"] is None
        assert _verification(slice_dir)["V03"]["verdict"] == "owed"


def test_a_settle_the_report_refuses_leaves_verification_json_as_it_was():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = _owed_slice(tmp, [_criterion("V17", DEPLOY, "owed")])
        _seed_owed(slice_dir, "V17", DEPLOY)                                     # A1
        _edit(slice_dir, "## ", "the operator's aside\n\n## ")
        verification = (slice_dir / "verification.json").read_bytes()
        files = _files(slice_dir)
        argv = ["settle", slice_dir, "V17", "--verdict", "pass", "--evidence", "e"]
        code, _, err = run_cli(*argv)
        assert code == 2 and err.startswith("Error: close-out.md was edited since")
        assert "  > the operator's aside\n" in err
        assert (slice_dir / "verification.json").read_bytes() == verification
        assert _files(slice_dir) == files
        code, _, err = run_cli(*argv, "--overwrite")
        assert code == 0, err
        assert _verification(slice_dir)["V17"]["verdict"] == "pass"
        assert entry_of(slice_dir, "A1")["strike"] is not None


# -- render ----------------------------------------------------------------------

def _heads(section_text):
    return re.findall(r"^### .*$", section_text, re.M)


def _section(text, title):
    start = text.index(f"\n## {title}\n")
    nxt = text.find("\n## ", start + 1)
    return text[start:nxt if nxt != -1 else len(text)]


def test_render_writes_the_sections_in_order_and_the_entries_in_their_forms():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        run_cli("append", slice_dir, *ACTION)                                    # A1
        run_cli("append", slice_dir, *with_flags(DEFECT, trigger="fault",
                                                 impact="severe"))                # B1
        run_cli("append", slice_dir, *DEFECT)                                    # B2
        close_out.request_card(slice_dir, "B2", "wrap-up", "needs design")
        run_cli("append", slice_dir, *with_flags(DEFECT, fix="one-edit",
                                                 area="plain"))                   # B3
        close_out.append_entry(slice_dir, "Bugs", "old", "old body",
                               consequence="c")                                  # B4
        run_cli("append", slice_dir, *with_flags(DEFECT, trigger="fault",
                                                 severity="nit"))                 # B5
        close_out.append_entry(slice_dir, "Notable events", "resumed", "ok",
                               consequence="none")                               # E1
        run_cli("append", slice_dir, *DEFECT)                                    # B6
        close_out.strike_entry(slice_dir, "B6", "dup of B2", by="consult 1",
                               commit="19640d9")
        for eid in ("A1", "B1", "B3", "B5", "E1", "B6"):
            close_out.add_note(slice_dir, eid, "consult 1", "a note for the record")
        line = close_out.render_report(slice_dir)
        assert line == ("Comes to you 2 · Card requests 1 · For the wrap-up 1 · "
                        "Unlabelled 1 · Closed 1 · Record 2")
        text = report(slice_dir)
        assert text.startswith("# Close-out — slice 007 argocd_tools_presync_hook\n\n"
                               "<!-- Generated by `close_out.py render` from "
                               "close-out.json")
        assert "\n     `close_out.py show <id>` prints an entry in full. -->\n" in text
        assert "\nRun: <not yet stamped>\n" in text
        titles = re.findall(r"^## (.+)$", text, re.M)
        assert titles == list(close_out.REPORT_SECTIONS)
        # the ask: the headline, the body, the Proposal, the Consequence, the
        # newest note, Triage and Provenance — and what the operator writes on;
        # the Proposal line only where there is one, the Route only where it
        # says more than the kind
        triage_b1 = ("**Triage:** defect · needs a fault · severe · silent · fix needs "
                     "design · sensitive area · in\nKubeCoder\n")
        assert _section(text, "Comes to you") == (
            "\n## Comes to you\n\n"
            "### A1 — controller: the status line is wrong\n\n"
            "the body\n\n"
            "**Proposal:** Do it before the next run: one command.\n\n"
            "**Consequence:** an operator reads a wrong status\n\n"
            "**Latest** (consult 1, " + close_out._today() + "): a note for the record\n\n"
            "**Triage:** action · shows on an ordinary condition · breaks a flow · silent\n"
            "**Provenance:** witnessed — code-reviewer, P3 r1\n"
            "**Disposition:**\n\n"
            "### B1 — controller: the status line is wrong\n\n"
            "the body\n\n"
            "**Consequence:** an operator reads a wrong status\n\n"
            "**Latest** (consult 1, " + close_out._today() + "): a note for the record\n\n"
            + triage_b1 +
            "**Provenance:** witnessed — code-reviewer, P3 r1\n"
            "**Route:** to you — a risk: severe, in place of a close\n"
            "**Disposition:**\n")
        assert "**Proposal:** needs design\n\n**Consequence:**" in \
            _section(text, "Card requests")
        assert ("**Latest** (wrap-up, " + close_out._today() + "): asks for a card: "
                "needs design\n\n") in _section(text, "Card requests")
        assert _section(text, "For the wrap-up") == (
            "\n## For the wrap-up\n\n"
            "### B3 — controller: the status line is wrong\n\n"
            "the body\n\n"
            "**Consequence:** an operator reads a wrong status\n\n"
            "**Latest** (consult 1, " + close_out._today() + "): a note for the record\n\n"
            "**Triage:** defect · shows on an ordinary condition · breaks a flow · silent "
            "· fix is one edit ·\nin KubeCoder\n"
            "**Provenance:** witnessed — code-reviewer, P3 r1\n"
            "**Route:** the wrap-up — fix\n**Disposition:**\n")
        assert _section(text, "Unlabelled") == (
            "\n## Unlabelled\n\n### B4 — old\n\nold body\n\n**Consequence:** c\n\n"
            "**Route:** none yet — the entry has no labels\n**Disposition:**\n")
        # closed: the heading, the Consequence unless it says none, Triage,
        # Provenance, the route, the Disposition line — not the body or a note
        assert _section(text, "Closed") == (
            "\n## Closed\n\n### B5 — controller: the status line is wrong · nit\n\n"
            "**Consequence:** an operator reads a wrong status\n\n"
            "**Triage:** defect · needs a fault · breaks a flow · silent · fix needs design "
            "· sensitive\narea · in KubeCoder\n"
            "**Provenance:** witnessed — code-reviewer, P3 r1\n"
            "**Route:** closed — it needs a fault\n**Disposition:**\n")
        # the record: headings alone, the events first, then what was struck
        assert _section(text, "Record") == (
            "\n## Record\n\n### E1 — resumed\n\n"
            "### ~~B6 — controller: the status line is wrong~~ — dup of B2 (19640d9); "
            "struck by consult 1\n")
        # an event's body and a struck entry's notes stay in the store
        assert "\nok\n" not in text and text.count("a note for the record") == 3
        assert "<details>" not in text
        # a render twice in a row writes the same bytes
        before = (slice_dir / "close-out.md").read_bytes()
        assert close_out.render_report(slice_dir) == line
        assert (slice_dir / "close-out.md").read_bytes() == before
        # a long proposal wraps at the report's width
        close_out.propose_entry(slice_dir, "B1", "wrap-up", " ".join(["a word"] * 30))
        close_out.render_report(slice_dir)
        comes = _section(report(slice_dir), "Comes to you")
        start = comes.index("**Proposal:** a word")
        block = comes[start:comes.index("\n\n**Consequence:** ", start)]
        assert len(block.splitlines()) > 1
        assert all(len(row) <= close_out.HEADER_WIDTH for row in block.splitlines())
        assert " ".join(block.split()) == "**Proposal:** " + " ".join(["a word"] * 30)


def test_render_orders_a_section_by_grade_then_kind_then_id():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        risky = with_flags(DEFECT, trigger="fault", impact="severe")
        for flags in (with_flags(risky, severity="nit"), risky,
                      with_flags(risky, severity="major"),
                      with_flags(risky, severity="minor"),
                      with_flags(risky, severity="cosmetic"),
                      with_flags(risky, kind="test-gap", severity="major")):
            run_cli("append", slice_dir, *flags)
        run_cli("append", slice_dir, *with_flags(DECISION, severity="major"))
        run_cli("append", slice_dir, *ACTION)
        close_out.render_report(slice_dir)
        heads = [h.split(" — ")[0][4:] for h in _heads(_section(report(slice_dir),
                                                                "Comes to you"))]
        assert heads == ["D1", "B3", "T1", "B4", "A1", "B2", "B1", "B5"]


def test_render_header_with_and_without_state_and_stamp():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        try:
            close_out.stamp_header(slice_dir)
            raise AssertionError("no state.json must raise")
        except ReportError as e:
            assert "state.json" in str(e)
        (slice_dir / "state.json").write_text(json.dumps(STATE))
        header = close_out.stamp_header(slice_dir)
        assert header == ("Run: 2026-08-14 19:49 → 23:53 · 11 phases (8 planned, "
                          "P9, P10, P11 appended) · 2 bail-outs · 1 test round · "
                          "doc phase done")
        text = report(slice_dir)
        assert "<not yet stamped>" not in text
        block = text[text.index("Run:"):]
        assert " ".join(block.split())[:len(header)] == header
        state = dict(STATE, cost={"cost_usd": 118.41, "planner_share": 0.18,
                                  "research_share": 0.04, "rework_share": 0.14})
        (slice_dir / "state.json").write_text(json.dumps(state))
        code, out, _ = run_cli("stamp", slice_dir)
        assert code == 0
        assert out.strip().endswith("· $118.41 (planner 18 %, research 4 %, rework 14 %)")
        assert report(slice_dir).count("Run:") == 1
        # wrapped at the report's width
        assert all(len(line) <= close_out.HEADER_WIDTH
                   for line in report(slice_dir).splitlines() if not line.startswith("<!--"))


def test_run_header_pieces():
    """What the state does not carry is left out; a bailed run names its
    stage; operator questions are counted among the bail-outs."""
    state = {"created_at": "2026-08-14T19:49:12+02:00",
             "updated_at": "2026-08-15T01:02:03+02:00",
             "run_phase": "bailed", "known_phases": ["1"], "test_rounds": 0}
    assert close_out.run_header(state) == (
        "Run: 2026-08-14 19:49 → 2026-08-15 01:02 · 1 phase · 0 test rounds · run bailed")
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        (slice_dir / "bailout.json").write_text("{}")
        assert close_out.run_header({"run_phase": "docs"}, slice_dir) == \
            "Run: run bailed in docs"
    state = dict(STATE, bailouts=[{"question": True}, {"question": False}])
    assert "2 bail-outs (1 operator question)" in close_out.run_header(state)
    assert "· 0 bail-outs ·" in close_out.run_header(dict(STATE, bailouts=[]))


def test_run_header_says_what_the_wrap_up_did():
    """After the doc phase's piece: `wrap-up landed` or `wrap-up left out`,
    nothing for a wrap-up nothing waited for. A project with no doc phase
    runs the ladder for the wrap-up alone (`writer: false`), and that is no
    doc phase done."""
    def header(**wrap_up):
        return close_out.run_header(dict(STATE, wrap_up=wrap_up))
    assert header(outcome="landed").endswith("· doc phase done · wrap-up landed")
    assert header(outcome="left_out", reason="the session timed out after 7200s"
                  ).endswith("· doc phase done · wrap-up left out")
    for quiet in (header(outcome="skipped"), header(outcome=None),
                  close_out.run_header(STATE)):
        assert "wrap-up" not in quiet
        assert quiet.endswith("· doc phase done")
    no_writer = dict(STATE, doc_phase={"stage": "done", "writer": False},
                     wrap_up={"outcome": "landed"})
    text = close_out.run_header(no_writer)
    assert "doc phase" not in text
    assert text.endswith("· 1 test round · wrap-up landed")


def test_the_route_follows_the_repositories_the_state_names():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        run_cli("append", slice_dir, *with_flags(DEFECT, repo="HelmCharts"))
        close_out.render_report(slice_dir)
        assert "## For the wrap-up" in report(slice_dir)
        (slice_dir / "state.json").write_text(json.dumps(STATE))
        close_out.render_report(slice_dir)
        cards = _section(report(slice_dir), "Card requests")
        assert "**Route:** card request — the fix lives in HelmCharts, which the " \
               "slice did not touch" in cards


# -- init, counts, list ------------------------------------------------------------

def test_init_creates_the_store_once_and_renders_it():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        code, out, _ = run_cli("init", slice_dir / "close-out.md")
        assert code == 0 and out.startswith("created ")
        assert report(slice_dir) == (
            "# Close-out — slice 007 argocd_tools_presync_hook\n\n"
            + close_out.HEAD_COMMENT + "\n\nRun: <not yet stamped>\n")
        assert store(slice_dir) == {"store": 1, "slice": "007_argocd_tools_presync_hook",
                                    "closed": None, "entries": [],
                                    "rendered": sha256(report(slice_dir))}
        run_cli("append", slice_dir, *DEFECT)
        assert close_out.init_report(slice_dir) is False
        assert len(store(slice_dir)["entries"]) == 1
        code, out, _ = run_cli("init", slice_dir)
        assert code == 0 and out.startswith("exists ")
        code, _, err = run_cli("counts", Path(tmp) / "nowhere")
        assert code == 2 and "not found" in err


def test_counts_live_entries_per_section_and_per_letter_on_one_line():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        assert close_out.counts_line(close_out.entry_counts(slice_dir)) == (
            "to you 0 · card requests 0 · wrap-up 0 · unlabelled 0 · closed 0 · record 0 "
            "— A 0 · D 0 · E 0 · B 0 · P 0 · T 0 · I 0")
        run_cli("append", slice_dir, *ACTION)
        run_cli("append", slice_dir, *DEFECT)
        run_cli("append", slice_dir, *DEFECT)
        run_cli("append", slice_dir, *with_flags(DEFECT, trigger="fault"))
        close_out.append_entry(slice_dir, "event", "resumed", "b", consequence="none")
        close_out.append_entry(slice_dir, "event", "struck", "b", consequence="none")
        close_out.append_entry(slice_dir, "defect", "unlabelled", "b")
        close_out.strike_entry(slice_dir, "B2", "dup")
        close_out.strike_entry(slice_dir, "E2", "dup")
        code, out, _ = run_cli("counts", slice_dir)
        assert out.strip() == (
            "to you 1 · card requests 0 · wrap-up 1 · unlabelled 1 · closed 1 · record 1 "
            "— A 1 · D 0 · E 1 · B 3 · P 0 · T 0 · I 0 · 1 entry without a Consequence "
            "line · 2 entries without a Provenance line")
        # what comes to the operator without a proposal: an action entered
        # without one, a risk; a card request has the wrap-up's words as its own
        close_out.append_entry(slice_dir, "action", "Do X", "b", consequence="none",
                               provenance="witnessed — the driver")            # A2
        line = close_out.counts_line(close_out.entry_counts(slice_dir))
        assert line.endswith("line · 1 entry that comes to you without a Proposal line")
        run_cli("append", slice_dir, *with_flags(DEFECT, trigger="fault",
                                                 impact="severe"))              # B5
        close_out.request_card(slice_dir, "B1", "wrap-up", "needs a design")
        counts = close_out.entry_counts(slice_dir)
        assert counts[close_out.NO_PROPOSAL] == 2
        assert close_out.counts_line(counts).endswith(
            " · 2 entries that come to you without a Proposal line")


def test_list_groups_by_kind_with_consequence_lines_and_struck_entries_marked():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        run_cli("append", slice_dir, *with_flags(DEFECT, severity="minor"))
        run_cli("append", slice_dir, *with_flags(DEFECT, severity="nit"))
        run_cli("append", slice_dir, *IMPROVEMENT)
        close_out.strike_entry(slice_dir, "B2", "duplicate of B1", by="consult 1")
        code, out, _ = run_cli("list", slice_dir)
        assert code == 0
        assert out.strip() == (
            "## action\n(none)\n## decision\n(none)\n## event\n(none)\n## defect\n"
            "B1 — controller: the status line is wrong · minor\n"
            "    Consequence: an operator reads a wrong status\n"
            "~~B2~~ — controller: the status line is wrong · nit — duplicate of B1; "
            "struck by consult 1\n"
            "## prose\n(none)\n## test-gap\n(none)\n## improvement\n"
            "I1 — drop the duplicate helper\n    Consequence: none")
        assert "the body" not in out


def test_show_prints_entries_in_full_by_id_or_every_live_one():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        run_cli("append", slice_dir, *ACTION)                                    # A1
        run_cli("append", slice_dir, *with_flags(DEFECT, severity="minor"))      # B1
        close_out.add_note(slice_dir, "B1", "consult 1", "still true after P4",
                           date="2026-10-01")
        close_out.leave_entry(slice_dir, "B1", "wrap-up", "the path is dead code",
                              date="2026-10-01")
        close_out.append_entry(slice_dir, "event", "resumed", "ok", consequence="none")
        run_cli("append", slice_dir, *DEFECT)                                    # B2
        close_out.strike_entry(slice_dir, "B2", "dup of B1", by="consult 1")
        close_out.rule_entry(slice_dir, "A1", words="do it")
        code, out, err = run_cli("show", slice_dir / "close-out.md", "B1", "A1")
        assert code == 0, err
        b1, a1 = out.rstrip("\n").split("\n\n### A1 — ")
        assert b1.startswith(
            "### B1 — controller: the status line is wrong · minor\n\nthe body\n\n"
            "consult 1, 2026-10-01 — still true after P4\n\n"
            "wrap-up, 2026-10-01 — looked and left it: the path is dead code\n\n"
            "**Consequence:** an operator reads a wrong status\n\n**Triage:** defect · ")
        assert b1.endswith(
            "\n**Provenance:** witnessed — code-reviewer, P3 r1\n"
            "**Route:** closed — the wrap-up looked and left it\n**Disposition:**")
        assert "**Proposal:**" not in b1
        assert a1.startswith(
            "controller: the status line is wrong\n\nthe body\n\n"
            "**Proposal:** Do it before the next run: one command.\n\n"
            "**Consequence:** an operator reads a wrong status\n\n"
            "**Triage:** action · shows on an ordinary condition · breaks a flow · silent\n"
            "**Provenance:** witnessed — code-reviewer, P3 r1\n"
            "**Route:** to you — an action\n**Disposition:** do it")
        # a struck entry by its id: its struck heading, no Route
        code, out, _ = run_cli("show", slice_dir, "B2")
        assert out.startswith("### ~~B2 — controller: the status line is wrong~~ — dup "
                              "of B1; struck by consult 1\n\nthe body\n\n")
        assert "**Route:**" not in out and "**Triage:** defect" in out
        # without an id: every live entry, under its section, in the report's order
        code, out, _ = run_cli("show", slice_dir)
        assert code == 0
        assert re.findall(r"^#{2,3} .*?(?= —|$)", out, re.M) == [
            "## Comes to you", "### A1", "## Closed", "### B1", "## Record", "### E1"]
        assert "ok\n\n**Consequence:** none" in out and "B2" not in out
        code, _, err = run_cli("show", slice_dir, "B9")
        assert code == 2 and "no entry B9" in err


# -- find_by_headline, live_entries ------------------------------------------------

def test_find_by_headline_and_live_entries_on_a_new_store():
    push = "Push HelmCharts by hand when its hold lifts"
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        close_out.append_entry(slice_dir, "Outstanding actions", push, "b",
                               consequence="none")
        close_out.append_entry(slice_dir, "Outstanding actions", "Settle V05", "b",
                               consequence="none")
        close_out.append_entry(slice_dir, "Bugs", "presync traceback", "b",
                               consequence="c", severity="minor")
        close_out.append_entry(slice_dir, "Notable events", "resumed", "b",
                               consequence="none")
        close_out.append_entry(slice_dir, "Open questions and rulings", "which", "b",
                               consequence="c")
        close_out.append_entry(slice_dir, "Suggestions", "an idea", "b", consequence="c")
        close_out.strike_entry(slice_dir, "A2", "settled")
        find = close_out.find_by_headline
        assert find(slice_dir, "Outstanding actions", " Push  HelmCharts by hand\nwhen "
                                                      "its hold lifts ") == "A1"
        assert find(slice_dir, "Outstanding actions", "Settle V05") == "A2"   # struck
        assert find(slice_dir, "action", push) == "A1"
        assert find(slice_dir, "Bugs", "presync traceback") == "B1"
        assert find(slice_dir, "Bugs", "presync traceback · minor") == "B1"
        assert find(slice_dir, "Notable events", "resumed") == "E1"
        assert find(slice_dir, "Open questions and rulings", "which") == "D1"
        assert find(slice_dir, "Suggestions", "an idea") == "I1"
        assert find(slice_dir, "Outstanding actions", "Push HelmCharts by hand") is None
        assert find(slice_dir, "Suggestions", push) is None
        live = close_out.live_entries
        assert live(slice_dir, "Outstanding actions") == [("A1", push)]
        assert live(slice_dir, "Bugs") == [("B1", "presync traceback · minor")]
        for section in ("Notable events", "Open questions and rulings", "Suggestions"):
            assert len(live(slice_dir, section)) == 1
        for section in ("Summary", "Nope"):
            try:
                live(slice_dir, section)
                raise AssertionError(f"{section} must raise")
            except ReportError:
                pass


OLD_REPORT = """\
# Close-out — slice 146 worker_robustness

<!-- Run header: stamped by the driver at close-out from state.json. Agents never edit it. -->
Run: 2026-08-15 20:28 → 21:46 · 4 phases

## Summary

What shipped, in a few lines.

## Outstanding actions

Focus: nothing is owed.

<!-- The operator runbook. -->

### A1 — Push HelmCharts by hand when its hold lifts

The hold stands.

**Consequence:** none in this run.

**Provenance:** witnessed — the driver
**Disposition:** done, pushed 2026-08-20

## Notable events

Focus: an uneventful run.

<!-- Everything that deviated. -->

### Consult 1 (2026-08-15) appended P4

The consult quoted the report it read:

```markdown
## Bugs

### B3 — not an entry
```

and moved on.

### N1 — the test phase was clean

Nothing to add.

**Consequence:** none

**Provenance:** read P4
**Disposition:**

## Bugs

Focus: the worst one first.

### B1 — the reset is unbounded · minor

Seen on the dev pod.

consult 1, 2026-08-15 — still true after P4.

**Consequence:** a failed build leaves layers
behind for the next one.

**Provenance:** read, code-reviewer P2 r1
**Disposition:** card KC

### ~~B2 — a traceback on a bad cert · nit~~ — resolved by P3 (abc123); struck by consult 1

<details><summary>struck — body kept for the record</summary>

The hook exits with a traceback.

**Consequence:** an operator sees a traceback.

**Provenance:** witnessed — P1 r1
**Disposition:**

</details>

### minor — a heading without an id

Hand-typed body.

## Open questions and rulings

Focus: none.

## Suggestions

### S1 — pin the image

**Consequence:** none

**Provenance:** read P2
**Disposition:**
"""


def test_import_reads_an_old_report_losing_nothing():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp, "146_worker_robustness")
        (slice_dir / "close-out.md").write_text(OLD_REPORT)
        code, out, err = run_cli("import", slice_dir)
        assert code == 0 and out.startswith("imported 7 entries"), err
        data = store(slice_dir)
        by_id = {e["id"]: e for e in data["entries"]}
        assert [e["id"] for e in data["entries"]] == ["A1", "N2", "N1", "B1", "B2", "B3",
                                                      "S1"]
        a1 = by_id["A1"]
        assert (a1["kind"], a1["section"]) == ("action", "Outstanding actions")
        assert a1["labels"] == dict.fromkeys(("trigger", "impact", "signal"), "none")
        assert a1["body"] == ["The hold stands."]
        assert a1["ruling"] == {"words": "done, pushed 2026-08-20", "did": None, "date": None}
        assert (a1["evidence"], a1["author"]) == ("witnessed", "the driver")
        # the heading without an id: the next id of the section's old letter,
        # its heading text as the headline, the fenced headings its body
        n2 = by_id["N2"]
        assert n2["headline"] == "Consult 1 (2026-08-15) appended P4"
        assert n2["kind"] == "event" and n2["consequence"] is None
        assert n2["body"] == ["The consult quoted the report it read:", "", "```markdown",
                              "## Bugs", "", "### B3 — not an entry", "```", "",
                              "and moved on."]
        b1 = by_id["B1"]
        assert (b1["kind"], b1["grade"], b1["labels"]) == ("defect", "minor", None)
        assert b1["body"] == ["Seen on the dev pod.", "",
                              "consult 1, 2026-08-15 — still true after P4."]
        assert b1["consequence"] == "a failed build leaves layers behind for the next one."
        assert b1["ruling"]["words"] == "card KC"
        b2 = by_id["B2"]
        assert b2["strike"] == {"reason": "resolved by P3 (abc123)", "by": "consult 1",
                                "date": None, "commit": None}
        assert (b2["headline"], b2["grade"]) == ("a traceback on a bad cert", "nit")
        assert b2["body"] == ["The hook exits with a traceback."]
        b3 = by_id["B3"]
        assert (b3["headline"], b3["body"]) == ("minor — a heading without an id",
                                                ["Hand-typed body."])
        assert by_id["S1"]["kind"] == "improvement" and by_id["S1"]["labels"] is None
        assert data["imported"]["Summary"] == ["What shipped, in a few lines."]
        assert data["imported"]["Bugs"] == ["Focus: the worst one first."]
        assert data["imported"]["Outstanding actions"][0] == "Focus: nothing is owed."
        # import refuses a second time
        code, _, err = run_cli("import", slice_dir)
        assert code == 2 and "exists" in err
        # the render: every id once, the operator's words kept, the Summary
        # and the Focus lines gone
        close_out.render_report(slice_dir)
        text = report(slice_dir)
        unfenced = [line for line, hidden in close_out._scan(text) if not hidden]
        for eid in by_id:
            assert len([h for h in unfenced
                        if re.match(rf"### (~~)?{eid} — ", h)]) == 1, eid
        # a body is the store's: the quoted heading in its fence is N2's, on the
        # page only where N2 is shown with its body
        assert "### B3 — not an entry" in close_out.show_view(slice_dir, ["N2"])
        assert all(e["proposal"] is None for e in data["entries"])
        assert "**Disposition:** card KC\n" in text
        assert "Focus:" not in text and "## Summary" not in text
        assert close_out.read_back(slice_dir) == []
        # counts: N and S listed after the new letters, as the store holds
        # them; Q not, as it holds none
        assert close_out.counts_line(close_out.entry_counts(slice_dir)).split(" — ")[1] \
            .startswith("A 1 · D 0 · E 0 · B 2 · P 0 · T 0 · I 0 · N 2 · S 1 · ")


def test_the_first_touch_imports_and_the_old_sections_still_find_their_entries():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp, "146_worker_robustness")
        (slice_dir / "close-out.md").write_text(OLD_REPORT)
        # an append on a slice with only the Markdown report imports it first
        assert close_out.append_entry(slice_dir, "Notable events", "resumed", "b",
                                      consequence="none") == "E1"
        assert (slice_dir / "close-out.json").exists()
        assert close_out.init_report(slice_dir) is False
        live = close_out.live_entries
        assert live(slice_dir, "Notable events") == [
            ("N2", "Consult 1 (2026-08-15) appended P4"),
            ("N1", "the test phase was clean"), ("E1", "resumed")]
        assert live(slice_dir, "Bugs") == [("B1", "the reset is unbounded · minor"),
                                           ("B3", "minor — a heading without an id")]
        assert live(slice_dir, "Suggestions") == [("S1", "pin the image")]
        assert live(slice_dir, "Open questions and rulings") == []
        find = close_out.find_by_headline
        assert find(slice_dir, "Outstanding actions",
                    "Push HelmCharts by hand when its hold lifts") == "A1"
        assert find(slice_dir, "Bugs", "a traceback on a bad cert · nit") == "B2"
        # relabelled to another kind, an imported entry still answers to its section
        close_out.relabel_entry(slice_dir, "N1", "wrap-up", "it was a gap",
                                kind="test-gap", labels={
                                    "trigger": "future-change", "impact": "degraded",
                                    "signal": "silent", "fix": "one-edit",
                                    "area": "plain", "repo": "KubeCoder"})
        assert find(slice_dir, "Notable events", "the test phase was clean") == "N1"
        # the worklist asks for the labels of what came in without any — but
        # not of B1, which the operator ruled on in the old report
        asked = {e["id"]: a.split(" — ")[0] for e, a in close_out.worklist(slice_dir)}
        assert asked["B3"] == "label" and asked["S1"] == "label"
        assert "B1" not in asked


# -- the lock ------------------------------------------------------------------------

def test_two_writers_interleaved_lose_nothing():
    """Every save made slow, so two writers without the lock would overwrite
    each other's work; with it, every append and every note lands."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        run_cli("append", slice_dir, *DEFECT)
        real_save = close_out._save

        def slow_save(d, data):
            time.sleep(0.002)
            real_save(d, data)

        errors: list[BaseException] = []

        def writer(n):
            try:
                for i in range(15):
                    close_out.append_entry(slice_dir, "event", f"w{n} e{i}", "b",
                                           consequence="none")
                    close_out.add_note(slice_dir, "B1", f"w{n}", f"note {i}")
            except BaseException as e:   # noqa: BLE001 — reported below
                errors.append(e)

        close_out._save = slow_save
        try:
            threads = [threading.Thread(target=writer, args=(n,), daemon=True)
                       for n in (1, 2)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=60)
            assert not any(t.is_alive() for t in threads), "a writer hung"
        finally:
            close_out._save = real_save
        assert not errors, errors
        data = store(slice_dir)
        headlines = [e["headline"] for e in data["entries"] if e["kind"] == "event"]
        assert sorted(headlines) == sorted(f"w{n} e{i}" for n in (1, 2) for i in range(15))
        ids = [e["id"] for e in data["entries"]]
        assert len(ids) == len(set(ids)) == 31
        assert len(data["entries"][0]["notes"]) == 30


def test_a_filesystem_without_the_lock_still_takes_the_write():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        real = close_out.fcntl.flock

        def refuse(fd, op):
            raise OSError(38, "Function not implemented")

        close_out.fcntl.flock = refuse
        try:
            assert run_cli("append", slice_dir, *DEFECT)[1].strip() == "B1"
        finally:
            close_out.fcntl.flock = real
        assert len(store(slice_dir)["entries"]) == 1


# -- the dispatch line, the verbs, and the docs --------------------------------------

def test_dispatch_line_is_the_text_with_the_labels_and_the_verbs_usage_in_it():
    report_md = "/specs/slices/007_x/close-out.md"
    line = close_out.dispatch_line(report_md)
    tool = str(Path(close_out.__file__).resolve())
    assert line.startswith(f"The slice's close-out report is {report_md}, rendered from "
                           "its store,\nclose-out.json. Write to it only through "
                           f"`python3 {tool} <verb> {report_md} …` —\n")
    assert ("`append`, `note`, `strike`; while it is not committed, `amend <id> --by\n"
            "<who>` corrects an entry you appended with that --by (any of `append`'s\n"
            "flags but --kind, each replacing its field), and `unnote` or `unstrike`\n"
            "takes back your own note or strike; `list` shows what is there\n"
            ) in line
    assert ("what you would do\n— never where the entry goes. "
            f"`python3 {tool} labels` prints what each\nlabel means —") in line
    assert ("read it before your first append. The labels each kind\ncarries, every "
            "one of them, `unknown` where you cannot tell:\n"
            + close_out.kind_labels_text() + "\n" + close_out.LABEL_PAIRING
            + "\nThe verbs take:\n"
            + close_out.verb_usage("append", "note", "strike", "unnote", "unstrike")
            + "\nThe report is about the work;") in line
    # every verb the line names to write with has its arguments in it
    for verb in ("append", "note", "strike", "unnote", "unstrike"):
        assert f"close_out.py {verb} <close-out.md>" in line, verb
    assert "close_out.py note <close-out.md> <id> --by BY --text TEXT" in line
    assert "--reason REASON [--by BY]" in line
    assert "close_out.py unnote <close-out.md> <id> --by BY\n" in line
    assert "close_out.py unstrike <close-out.md> <id> --by BY\n" in line
    assert line.endswith("goes to the `fieldnotes` MCP tool\n`post` instead.")


def test_verb_usage_renders_append_compactly_with_its_help_strings():
    block = close_out.verb_usage("append")
    lines = block.splitlines()
    assert lines[0].startswith("close_out.py append <close-out.md> --kind {action,decision,"
                               "event,defect,prose,test-gap,improvement} --headline HEADLINE")
    assert " [-h]" not in block
    assert "--section" not in block
    assert "[--repo NAME]" in lines[0] and "[--for SLICE]" in lines[0]
    assert "[--product-call {yes,no}]" in lines[0]
    assert "--consequence CONSEQUENCE [--proposal PROPOSAL] [--provenance" in lines[0]
    assert len(lines) == 1 + 21
    for flag, help_ in (
            ("--kind", "what the entry is — it decides which of the labels below the "
                       "entry carries"),
            ("--headline", "one line, the claim itself — the ask, as the operator reads "
                           "it: a defect names its repo or component, an action is an "
                           "imperative, a decision asks its question, an improvement "
                           "says what it proposes"),
            ("--body", "entry body, or - for stdin"),
            ("--consequence", "what an operator or user experiences if this stays as it "
                              "is, or none — the line the operator triages on"),
            ("--proposal", "what you would do about it and why, in a sentence or two, in "
                           "a ruling's words (card · fix now · fold into <slice> · close · "
                           "do it) — the operator reads it with the headline and the "
                           "Consequence and nothing else; required for an action, a "
                           "decision and an improvement"),
            ("--provenance", "witnessed | read, then role, phase, round, and the "
                             "artifact with the full record"),
            ("--by", "who appends — role, phase and round; an entry appended with --by "
                     "can be corrected with amend until it is committed, one without it "
                     "cannot"),
            ("--severity", "the grade, where the entry has one"),
            ("--trigger", "what has to happen for the problem to show"),
            ("--impact", "what is then experienced"),
            ("--signal", "whether it then says so itself"),
            ("--fix", "what is decided about the fix"),
            ("--area", "sensitive: concurrency or timing, stored data, a wire contract, "
                       "authentication or secrets"),
            ("--repo", "the repository the fix lives in, by its directory name"),
            ("--for", "the number of another slice, still to run, that should take "
                      "the entry — never the slice being run; leave it out for an "
                      "entry about this one. One already planned or running brings "
                      "the entry to the operator, since that run never reads slice.md"),
            ("--benefit", "improvement: who is better off"),
            ("--felt", "improvement: when that is felt"),
            ("--change", "improvement: whether it removes, adjusts or adds"),
            ("--size", "improvement: what the change takes"),
            ("--product-call", "improvement: whether it changes what a user of the "
                               "product sees or can do"),
            ("--prevents", "improvement: the worst it would prevent")):
        assert f"    {flag}: {help_}" in lines, flag
    wrap_up = close_out.verb_usage("show", "propose", "request-card").splitlines()
    assert wrap_up[0] == "close_out.py show <close-out.md> [<id> ...]"
    assert ("close_out.py propose <close-out.md> <id> --by BY --text TEXT "
            "[--date DATE]") in wrap_up
    for help_ in ("    --by: who proposes",
                  "    --text: what you would do about it and why, or - for stdin",
                  "    --text: how it is reached and what the fix takes — it becomes the "
                  "entry's proposal; or - for stdin"):
        assert help_ in wrap_up, help_
    notes = close_out.verb_usage("list", "note", "strike")
    assert notes.splitlines()[0] == "close_out.py list <close-out.md>"
    assert "    <id>: the entry's id, like B3" in notes
    assert "slice:" not in notes and "<close-out.md>:" not in notes


def test_kind_labels_are_what_append_refuses_without():
    # The block a dispatch carries is rendered from REQUIRED and
    # EVENT_PROBLEM — the tables check_labels refuses from.
    assert close_out.kind_labels_text().splitlines() == [
        "  action, decision: --trigger, --impact and --signal",
        "  event: --trigger, --impact and --signal; with an --impact other than "
        "none also --fix, --area and --repo",
        "  defect, test-gap: --trigger, --impact, --signal, --fix, --area and --repo",
        "  prose: --trigger, --impact, --signal, --fix and --repo",
        "  improvement: --benefit, --felt, --change, --size, --product-call, "
        "--prevents, --area and --repo"]
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        for kind, line in (("decision", "--trigger, --impact and --signal"),
                           ("prose", "--fix and --repo")):
            errors = close_out.check_labels(kind, {}, "none", slice_dir)
            assert errors and line in errors[0], (kind, errors)


def test_verb_usage_puts_the_positionals_right_after_the_verb():
    # argparse renders positionals last; agents read the line as the call's
    # shape and typed a trailing `slice` literally or put the id first.
    strike = close_out.verb_usage("strike").splitlines()
    assert strike[0] == ("close_out.py strike <close-out.md> <id> --reason REASON "
                         "[--by BY] [--commit COMMIT] [--date DATE]")
    assert strike[1] == "    <id>: the entry's id, like B3"
    rule = close_out.verb_usage("rule").splitlines()[0]
    assert rule.startswith("close_out.py rule <close-out.md> [<id>] [--words WORDS]")
    assert close_out.verb_usage("note").splitlines()[0].startswith(
        "close_out.py note <close-out.md> <id> --by BY --text TEXT")
    assert close_out.verb_usage("unnote", "unstrike").splitlines() == [
        "close_out.py unnote <close-out.md> <id> --by BY",
        "    <id>: the entry's id, like B3",
        "    --by: the --by the note was written with — a relabel's labels go back with it",
        "close_out.py unstrike <close-out.md> <id> --by BY",
        "    <id>: the entry's id, like B3",
        "    --by: the --by the strike was made with"]
    # The CLI's own usage — what an argument error prints — has the same shape.
    _, subs = close_out.build_parser()
    assert subs["strike"].format_usage().startswith(
        "usage: close_out.py strike <close-out.md> <id> [-h] --reason REASON")


def test_labels_prints_the_contracts_labels_section():
    code, out, _ = run_cli("labels")
    assert code == 0
    doc = close_out.CONTRACT_DOC.read_text()
    assert out.startswith("## The labels\n")
    assert out.rstrip("\n") in doc
    assert "\n## " not in out


def _labels_section():
    doc = close_out.CONTRACT_DOC.read_text()
    start = doc.index("\n## The labels\n")
    return doc[start:doc.index("\n## ", start + 1)]


def test_the_contract_and_the_tool_agree_on_every_label_value():
    section = _labels_section()
    ticked = set(re.findall(r"`([^`]+)`", section))
    accepted = {v for values in close_out.LABELS.values() if values for v in values}
    accepted |= set(close_out.KINDS)
    missing = accepted - ticked
    assert not missing, f"values the tool accepts that the contract does not name: {missing}"
    # every value the section's tables name — the value column of the label
    # tables, the kind column of the kinds table — is one the tool accepts
    named: dict[str, set[str]] = {}
    label = None
    for row in re.findall(r"^\|(.+)\|\s*$", section, re.M):
        cells = [c.strip() for c in row.split("|")]
        if set(cells[0]) <= set("-: ") or cells[0] in ("kind", "label"):
            continue
        first = re.findall(r"`([^`]+)`", cells[0])
        if len(cells) == 3 and cells[1] in close_out.KINDS.values():
            named.setdefault("kind", set()).update(first)
            continue
        if len(cells) >= 3 and (first or label):
            if first and (first[0] in close_out.LABELS):
                label = first[0]
            if label:
                named.setdefault(label, set()).update(re.findall(r"`([^`]+)`", cells[1]))
    assert named["kind"] == set(close_out.KINDS)
    for label, values in named.items():
        if label == "kind":
            continue
        allowed = close_out.LABELS[label]
        assert allowed is not None or not values, label
        assert values <= set(allowed or ()), (label, values - set(allowed or ()))
    assert set(named) >= set(close_out.LABELS) - {"repo", "for"} | {"kind"}


def test_the_template_and_the_tool_agree_on_the_sections_and_the_verbs():
    doc = close_out.TEMPLATE_DOC.read_text()
    skeleton = re.search(r"^```markdown\n(# Close-out.*?)^```", doc, re.S | re.M).group(1)
    assert re.findall(r"^## (.+)$", skeleton, re.M) == list(close_out.REPORT_SECTIONS)
    verbs_doc = doc[doc.index("## The verbs"):]
    in_doc = re.findall(r"^\| `([a-z-]+)` \|", verbs_doc, re.M)
    _, subs = close_out.build_parser()
    assert sorted(in_doc) == sorted(subs)


def test_slice_dir_of_accepts_the_directory_the_report_or_the_store():
    assert close_out.slice_dir_of("/s/007_x") == Path("/s/007_x")
    assert close_out.slice_dir_of("/s/007_x/close-out.md") == Path("/s/007_x")
    assert close_out.slice_dir_of("/s/007_x/close-out.json") == Path("/s/007_x")


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
