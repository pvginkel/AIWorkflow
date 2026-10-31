"""Tests for close_out — the close-out report's store, routes and render.

A throwaway slice folder per test, under a `slices/` directory so `--for`
has slices to name; the contract and the template are read from the
plugin's own docs, so a doc edit the tool no longer agrees with fails here.
Stdlib only; runs standalone and under pytest.

Run: `python3 ${CLAUDE_PLUGIN_ROOT}/tools/test_close_out.py` or via pytest.
"""

import contextlib
import difflib
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
DECISION = [*with_flags(ACTION, kind="decision", proposal=None),
            "--option", "Keep it", "nothing changes",
            "--option", "Change it", "costs a release",
            "--recommend", "Keep it"]


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


# The slice folders as `slice_stages` gives them: 012 unplanned, 051 planned
# or running, 002 run already, 007 the slice itself; no folder holds 077.
PENDING = {12: ("012", "unplanned"), 51: ("051", "planned"), 2: ("002", "past"),
           7: ("007", "own")}
HELD_77 = ("operator:held", "to you — for slice 077, which no folder holds yet: hold it "
           "for that slice")
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
        # the slice itself, and a value that names no slice: as without `for`
        assert at("007")[0] == at("none")[0] == without
        # no folder at all: held until triage creates the slice
        assert at("077") == HELD_77
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


def test_owed_before_push_without_a_store_is_a_report_error():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        try:
            close_out.owed_before_push(slice_dir)
            raise AssertionError("no store must raise")
        except ReportError as e:
            assert "close_out.py init" in str(e)


# -- to fix before the test phase --------------------------------------------------

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


def test_the_cli_refuses_an_authors_line_number_and_the_loops_api_does_not():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        _refused(slice_dir, with_flags(DEFECT, body="it breaks at controller.py:88"),
                 "--body cites a line by its number (`controller.py:88`)",
                 "spec-tree.md § Citing a line")
        _refused(slice_dir, with_flags(DEFECT, consequence="status.go:12 shows it wrong"),
                 "--consequence cites")
        _refused(slice_dir, with_flags(IMPROVEMENT, proposal="Drop helpers.py:3-9 now."),
                 "--proposal cites")
        # a command's output in a fenced block is evidence, not a citation
        code, out, err = run_cli("append", slice_dir, *with_flags(
            DEFECT, body="the gate:\n\n```\ntests/t.py:4: AssertionError\n```"))
        assert code == 0, err
        eid = out.strip()
        # an amend is checked on what it changes
        code, _, err = run_cli("amend", slice_dir, eid, "--body", "now in x.py:3")
        assert code == 2 and "--body cites" in err, err
        code, _, err = run_cli("amend", slice_dir, eid, "--headline", "controller: wrong")
        assert code == 0, err
        for argv, says in [
            (("note", slice_dir, eid, "--by", "me", "--text", "see w.py:1"), "the note cites"),
            (("note", slice_dir, eid, "--by", "me", "--left", "--text", "w.py:1"),
             "the note cites"),
            (("propose", slice_dir, eid, "--by", "me", "--text", "fix v.py:2"),
             "the proposal cites"),
        ]:
            code, _, err = run_cli(*argv)
            assert code == 2 and says in err, (argv, err)
        assert entry_of(slice_dir, eid)["notes"] == []
        # the loops' API quotes tool output and is not checked
        close_out.add_note(slice_dir, eid, "the run loop", "the gate said x.py:3")
        close_out.append_entry(slice_dir, "event", "the gate failed", "at y.py:9",
                               consequence="none")


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


def test_append_refuses_a_for_naming_the_slice_itself_or_one_no_longer_to_run():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        # `none` clears a relabel's `for`; an append stores no "none"
        _refused(slice_dir, with_flags(DEFECT, **{"for": "none"}),
                 "--for none names no slice",
                 "--for names another slice that should take the entry — one still "
                 "to run, or one triage has not created yet, which holds the entry "
                 "until it does — never the slice being run: leave it out for an "
                 "entry about this one; an entry for a slice already planned or "
                 "running comes to the operator, since that run never reads slice.md")
        # a completed slice is not still to run, and neither is the slice
        # itself — which the refusal names as the slice being run
        _refused(slice_dir, with_flags(DEFECT, **{"for": "2"}),
                 "--for 2: slice 002 is no longer to run — its folder is outside "
                 "slices/ and slices/backlog/ (it has run, or was cancelled)")
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


def test_slice_stages_carries_each_slice_still_to_run_with_its_stage():
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
        to_run = {n: stage for n, stage in close_out.slice_stages(slice_dir).items()
                  if stage[1] in ("planned", "unplanned")}
        assert to_run == {
            12: ("012", "unplanned"), 13: ("013", "planned"), 31: ("031", "unplanned"),
            40: ("040", "planned"), 41: ("041", "unplanned"), 42: ("042", "unplanned")}
        assert close_out.slice_stages(Path(tmp) / "007_x") is None


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
        assert places(slice_dir) == {"Comes to you": ["B1", "I1"]}
        assert route_of(slice_dir, "B1") == route_of(slice_dir, "I1") == FOR_PLANNED


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
        assert data["store"] == 2 and data["slice"] == "007_argocd_tools_presync_hook"
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
        # no temp file left beside it, and nothing rendered on a write
        assert sorted(p.name for p in slice_dir.iterdir()) == ["close-out.json"]
        # without --proposal, a defect stores none
        code, out, _ = run_cli("append", slice_dir, *DEFECT)
        assert entry_of(slice_dir, out.strip())["proposal"] is None
        # the block's fields only where given, after the rest
        code, out, err = run_cli("append", slice_dir, *ACTION, "--check", "env JOB_TOKEN",
                                 "--check", "slice 12 completed", "--due", "Push",
                                 "--option", "Done", "--option", "Not possible", "say why")
        assert code == 0, err
        a1 = entry_of(slice_dir, out.strip())
        assert list(a1)[-4:] == ["ruling", "options", "check", "due"]
        assert a1["options"] == [{"label": "Done"},
                                 {"label": "Not possible", "line": "say why"}]
        assert (a1["check"], a1["due"]) == ("env JOB_TOKEN; slice 12 completed", "push")


def test_an_actions_check_is_the_vocabularys_and_one_before_the_run_needs_one():
    """AIWF-88: an action's check is a fact the tree or the pod shows — never
    a commit, which a push rebases, nor an environment, which may not be the
    one that runs the slice — and an action owed before the run states one,
    or says `manual`."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        _refused(slice_dir, [*ACTION, "--check", "the job runs"],
                 "--check: `the job runs` is no check", "`slice <NNN> completed`")
        _refused(slice_dir, [*ACTION, "--check", "origin . main:x contains 45a9ab3"],
                 "45a9ab3, a commit")
        _refused(slice_dir, [*ACTION, "--check", "manual", "--check", "env A"],
                 "`manual` stands alone")
        prerun = with_flags(ACTION, headline="Before /dev:run-slice: restart the pod")
        _refused(slice_dir, prerun, "an action owed before the run needs --check")
        _refused(slice_dir, [*prerun, "--check", "restart pvginkel-pilotapp-addac6"],
                 "an environment")
        code, out, err = run_cli("append", slice_dir, *prerun,
                                 "--check", "env PILOT_TOKEN", "--check",
                                 "origin ../PilotApp main:.kubecoder/config.yaml "
                                 "contains PILOT_TOKEN")
        assert code == 0, err
        assert entry_of(slice_dir, "A1")["check"] == (
            "env PILOT_TOKEN; origin ../PilotApp main:.kubecoder/config.yaml "
            "contains PILOT_TOKEN")
        code, out, err = run_cli("append", slice_dir, *with_flags(
            prerun, headline="Before `/dev:run-slice`: approve the spend"),
            "--check", "manual")
        assert code == 0, err
        # an action after the run may go without one
        assert run_cli("append", slice_dir, *ACTION)[0] == 0
        # the loops' own path takes a pre-run action without one: the run
        # loop reads it as one a person strikes
        close_out.append_entry(slice_dir, "action", "Before /dev:run-slice: x", "b",
                               consequence="c")
        assert [(a["id"], a["check"], a["struck"])
                for a in close_out.prerun_actions(slice_dir)] == [
            ("A1", entry_of(slice_dir, "A1")["check"], False),
            ("A2", "manual", False), ("A4", None, False)]
        close_out.strike_entry(slice_dir, "A2", "approved", by="op")
        assert [a["struck"] for a in close_out.prerun_actions(slice_dir)] == \
            [False, True, False]
    assert close_out.prerun_actions(Path("/nonexistent")) == []


def test_append_asks_a_proposal_of_an_action_a_decision_and_an_improvement():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        for base, article in ((ACTION, "an action"), (IMPROVEMENT, "an improvement")):
            for missing in (None, " \n "):
                _refused(slice_dir, with_flags(base, proposal=missing),
                         f"Error: {article} needs --proposal: what you would do about "
                         "it and why, in a sentence or two")
        # said with the label refusals, in one error
        err = _refused(slice_dir, with_flags(IMPROVEMENT, proposal=None, felt=None),
                       "missing: --felt", "an improvement needs --proposal")
        assert err.count("Error:") == 1
        # a decision owes its options, two or more, and the one it recommends, and
        # takes no proposal
        bare = with_flags(ACTION, kind="decision", proposal=None)
        _refused(slice_dir, bare, "a decision needs its --option lines, two or more")
        _refused(slice_dir, [*bare, "--option", "Keep", "--recommend", "Keep"],
                 "a decision puts two options or more")
        _refused(slice_dir, [*bare, "--option", "Keep", "--option", "Change"],
                 "a decision needs --recommend")
        _refused(slice_dir, [*bare, "--option", "Keep", "--option", "Change",
                             "--recommend", "Drop"], "--recommend 'Drop' names no --option")
        _refused(slice_dir, [*DECISION, "--proposal", "Keep it."],
                 "a decision takes no --proposal")
        _refused(slice_dir, [*bare, "--option", "Keep", "a", "b"],
                 "--option takes a label and one line")
        # a question in an improvement's headline makes it a decision
        _refused(slice_dir, with_flags(IMPROVEMENT, headline="Drop the duplicate helper?"),
                 "a question in an improvement's headline makes it a decision")
        # the block's fields by kind
        _refused(slice_dir, [*DEFECT, "--check", "x"], "--check is an action's")
        _refused(slice_dir, [*DEFECT, "--recommend", "x"], "--recommend is a decision's")
        _refused(slice_dir, [*IMPROVEMENT, "--option", "a", "--option", "b"],
                 "--option is a decision or an action's")
        code, out, err = run_cli("append", slice_dir, *DECISION)
        assert code == 0 and out.strip() == "D1", err
        # a defect, prose, a test gap and an event owe none, and any kind takes --due
        for argv in (DEFECT, with_flags(DEFECT, kind="prose", area=None),
                     with_flags(DEFECT, kind="test-gap", due="test"),
                     with_flags(ACTION, kind="event", proposal=None, consequence="none",
                                trigger="none", impact="none", signal="none")):
            code, _, err = run_cli("append", slice_dir, *argv)
            assert code == 0, err
        # the loops' path refuses nothing about the proposal
        assert close_out.append_entry(slice_dir, "action", "Do X", "b",
                                      consequence="none") == "A1"
        assert entry_of(slice_dir, "A1")["proposal"] is None
        assert close_out.append_entry(slice_dir, "action", "Do Y", "b", consequence="none",
                                      proposal=" Do it\n now. ", due="push") == "A2"
        assert entry_of(slice_dir, "A2")["proposal"] == "Do it now."
        # ...but a field its kind does not take, it refuses too
        try:
            close_out.append_entry(slice_dir, "defect", "x", "b", check="y")
            raise AssertionError("a defect's check must raise")
        except ReportError as e:
            assert "--check is an action's" in str(e)


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
        assert places(slice_dir) == {"Comes to you": ["A1", "D1"],
                                     "For the wrap-up": ["E2"],
                                     "Unlabelled": ["B1", "I1"], "Record": ["E1"]}
        assert route_of(slice_dir, "E2")[1] == \
            "the wrap-up — look: its trigger and impact are unknown"
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
        code, _, err = run_cli(*relabel, "--for", "002")
        assert code == 2 and "--for 002: slice 002 is no longer to run" in err
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
                              (("--for", "002"), "--for 002")):
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
        # a `for` the call gives is checked, the slices that ran refused
        for target, written in (("12", "012"), ("2", "002")):
            code, _, err = run_cli(*relabel, "--for", target)
            assert code == 2 and f"--for {target}: slice {written} is no longer to " \
                "run" in err, err
        # one no folder holds is taken, at the width the folders are written in
        code, _, err = run_cli(*relabel, "--for", "77")
        assert code == 0, err
        assert entry_of(slice_dir, "B1")["labels"]["for"] == "077"
        code, _, err = run_cli(*relabel, "--for", "31")
        assert code == 0, err
        assert entry_of(slice_dir, "B1")["labels"]["for"] == "031"


# -- unnote, unstrike: an author takes back what is not committed ------------------

def git(cwd, *args):
    """git with an identity and no signing, whatever the host's config says."""
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t",
                    "-c", "commit.gpgsign=false", *args],
                   cwd=cwd, check=True, capture_output=True)


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
        assert not (slice_dir / "close-out.md").exists()
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
        # the Python API is the same call, and anyone amends: --by replaces the author
        assert close_out.amend_entry(slice_dir, "B1", headline="h") == "### B1 — h · nit"
        assert entry_of(slice_dir, "B1")["headline"] == "h"
        assert _amend(slice_dir, "B1", "--severity", "minor", by="wrap-up")[0] == 0
        assert entry_of(slice_dir, "B1")["by"] == "wrap-up"
        # a struck entry is settled: a note adds to it
        close_out.strike_entry(slice_dir, "B1", "fixed")
        _amend_refused(slice_dir, "B1", ["--headline", "x"], "B1 is struck")


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
        _amend_refused(slice_dir, "B1", ["--for", "002"],
                       "--for 002: slice 002 is no longer to run")
        run_cli("append", slice_dir, *IMPROVEMENT, "--by", BY)                      # I1
        _amend_refused(slice_dir, "I1", ["--trigger", "fault"],
                       "--trigger: not a label of an improvement")
        # an action and an improvement keep their proposal, a decision its options
        run_cli("append", slice_dir, *ACTION, "--by", BY)                           # A1
        run_cli("append", slice_dir, *DECISION, "--by", BY)                         # D1
        for eid, article in (("A1", "an action"), ("I1", "an improvement")):
            for empty in ("", " \n "):
                _amend_refused(slice_dir, eid, ["--proposal", empty],
                               f"Error: {article} needs --proposal: what you would do "
                               "about it and why, in a sentence or two")
        _amend_refused(slice_dir, "D1", ["--option", "Only one"],
                       "a decision puts two options or more")
        _amend_refused(slice_dir, "D1", ["--recommend", "Drop"], "names no --option")
        _amend_refused(slice_dir, "D1", ["--proposal", "Keep."],
                       "a decision takes no --proposal")
        assert _amend(slice_dir, "D1", "--option", "A", "--option", "B", "--recommend",
                      "B")[0] == 0
        assert entry_of(slice_dir, "D1")["options"] == [{"label": "A"}, {"label": "B"}]
        _amend_refused(slice_dir, "A1", ["--due", "never"], "invalid choice")
        assert _amend(slice_dir, "A1", "--due", "test", "--check", "manual")[0] == 0
        assert (entry_of(slice_dir, "A1")["due"], entry_of(slice_dir, "A1")["check"]) == \
            ("test", "manual")
        assert _amend(slice_dir, "A1", "--check", "")[0] == 0
        assert "check" not in entry_of(slice_dir, "A1")
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


# -- the wrap-up: marks and worklist ---------------------------------------------

def test_a_card_request_and_leave_mark_the_entry_and_the_card_is_its_proposal():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        run_cli("append", slice_dir, *DEFECT)                                  # B1
        run_cli("append", slice_dir, *with_flags(DEFECT, fix="one-edit",
                                                 area="plain"))                 # B2
        close_out.propose_entry(slice_dir, "B1", "code-reviewer, P3 r1",
                                "Close it: it needs a fault.", date="2026-09-30")
        # a card request is the section Agree files: the entry restated first
        code, _, err = run_cli("propose", slice_dir, "B1", "--by", "wrap-up", "--card",
                               "--text", "Card it.")
        assert code == 2 and "B1 is not restated" in err and "`restate` it first" in err
        restated(slice_dir, "B1")
        code, out, err = run_cli("propose", slice_dir, "B1", "--by", "wrap-up", "--card",
                                 "--text", "reached on every restart;\nneeds a design",
                                 "--date", "2026-09-30")
        assert code == 0, err
        assert out.strip() == "**Proposal:** reached on every restart; needs a design"
        b1 = entry_of(slice_dir, "B1")
        assert b1["wrap_up"] == {
            "outcome": "card", "by": "wrap-up", "date": "2026-09-30",
            "text": ["reached on every restart;", "needs a design"]}
        # the card request is the entry's proposal; the one it replaced is a note
        assert b1["proposal"] == "reached on every restart; needs a design"
        assert b1["notes"] == [{"by": "wrap-up", "date": "2026-09-30",
                                "text": ["proposal replaced — was: Close it: it needs a "
                                         "fault."], "history": "proposal"}]
        code, out, err = run_cli("note", slice_dir, "B2", "--by", "wrap-up", "--left",
                                 "--text", "the path is dead code", "--date", "2026-09-30")
        assert code == 0, err
        assert out.strip() == "wrap-up, 2026-09-30 — looked and left it: the path is dead code"
        assert entry_of(slice_dir, "B2")["proposal"] is None
        assert entry_of(slice_dir, "B2")["notes"] == []
        assert route_of(slice_dir, "B1") == ("card:wrap-up",
                                             "card request — the wrap-up asks for a card")
        assert route_of(slice_dir, "B2") == ("closed:left",
                                             "closed — the wrap-up looked and left it")
        assert places(slice_dir) == {"Card requests": ["B1"], "Closed": ["B2"]}
        # a second mark replaces the first, which stays as a history note
        close_out.leave_entry(slice_dir, "B1", "wrap-up", "not likely", date="2026-10-01")
        b1 = entry_of(slice_dir, "B1")
        assert b1["wrap_up"]["outcome"] == "left"
        assert b1["notes"][-1] == {"by": "wrap-up", "date": "2026-09-30",
                                   "text": ["asks for a card: reached on every restart;",
                                            "needs a design"], "history": "wrap-up"}
        # the marks are among the notes of the full view
        shown = close_out.show_view(slice_dir, ["B1", "B2"])
        assert "wrap-up, 2026-10-01 — looked and left it: not likely" in shown
        assert "wrap-up, 2026-09-30 — looked and left it: the path is dead code" in shown
        # a struck entry takes no mark
        close_out.strike_entry(slice_dir, "B2", "gone")
        code, _, err = run_cli("note", slice_dir, "B2", "--by", "w", "--left", "--text", "t")
        assert code == 2 and "struck" in err
        code, _, err = run_cli("propose", slice_dir, "B2", "--by", "w", "--card",
                               "--text", "t")
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
        assert "```action id=A1" in report(slice_dir)
        assert "**Proposal:**" not in report(slice_dir)
        assert "**Proposal:**" not in close_out.show_view(slice_dir, ["A1"])
        assert close_out.entry_counts(slice_dir)[close_out.NO_PROPOSAL] == 1
        close_out.propose_entry(slice_dir, "A1", "the operator", "Do it.")
        assert entry_of(slice_dir, "A1")["proposal"] == "Do it."
        assert entry_of(slice_dir, "A1")["notes"] == []


WU = "wrap-up"


def restated(slice_dir, eid, headline="the ask, as the wrap-up puts it",
             body="the story as it stands", date="2026-09-30"):
    """The restatement a card or a word request takes before its proposal."""
    return close_out.restate_entry(slice_dir, eid, WU, headline, body, date=date)
EASY = with_flags(DEFECT, fix="one-edit", area="plain")     # the wrap-up's, to fix
WORD = ("design/engine-and-sync.md, the line \"The engine syncs on demand.\" — say it syncs "
        "on start; a design record is corrected on the operator's word (CLAUDE.md § Design "
        "records)")
WORD_ROUTE = ("operator:word", "to you — the wrap-up asks for your word on its edit")


def test_a_word_request_brings_the_entry_to_the_operator_whatever_the_table_said():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        run_cli("append", slice_dir, *EASY)                                      # B1
        run_cli("append", slice_dir, *with_flags(DEFECT, trigger="fault"))       # B2
        assert route_of(slice_dir, "B1")[0] == "wrap-up:fix"
        assert route_of(slice_dir, "B2")[0].startswith("closed:")
        restated(slice_dir, "B1")
        restated(slice_dir, "B2")
        code, out, err = run_cli("propose", slice_dir, "B1", "--by", WU, "--word", "--text",
                                 "-", "--date", "2026-10-24", stdin=WORD + "\n")
        assert code == 0, err
        assert out == f"**Proposal:** {WORD}\n"
        close_out.propose_entry(slice_dir, "B2", WU, WORD, date="2026-10-24", mark="word")
        b1 = entry_of(slice_dir, "B1")
        assert b1["wrap_up"] == {"outcome": "word", "by": WU, "date": "2026-10-24",
                                 "text": [WORD]}
        # its words are the proposal the operator's assent executes
        assert b1["proposal"] == WORD and "proposed" not in b1
        for eid in ("B1", "B2"):
            assert route_of(slice_dir, eid) == WORD_ROUTE
        assert places(slice_dir) == {"Comes to you": ["B1", "B2"]}
        counts = close_out.entry_counts(slice_dir)
        assert (counts["to you"], counts["wrap-up"], counts["closed"],
                counts[close_out.NO_PROPOSAL]) == (2, 0, 0, 0)
        assert close_out.counts_line(counts).startswith(
            "to you 2 · card requests 0 · wrap-up 0 · unlabelled 0 · closed 0")
        # a marked entry waits for nothing
        assert close_out.worklist(slice_dir) == []
        assert f"**Route:** {WORD_ROUTE[1]}" in close_out.show_view(slice_dir, ["B1"])
        # the document asks for the word as the proposal of a decision
        close_out.render_report(slice_dir)
        doc = report(slice_dir)
        assert doc.count(f"```decision id=B1\nproposal: {close_out.asks.scalar(WORD)}\n```") \
            == 1
        assert close_out.verb_usage("propose").splitlines()[0] == (
            "close_out.py propose <close-out.md> <id> --by BY --text TEXT [--card | --word] "
            "[--date DATE]")


def test_restate_gives_the_section_and_the_record_keeps_the_authors_text():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        run_cli("append", slice_dir, *with_flags(DEFECT, severity="minor",
                                                 trigger="normal-use"))       # B1
        close_out.add_note(slice_dir, "B1", "consult 1", "not owed as a phase",
                           date="2026-10-31")
        restate = ("restate", slice_dir, "B1", "--by", WU, "--date", "2026-10-31")
        code, out, err = run_cli(
            *restate, "--headline", "Card it: the status line is wrong after every restart",
            "--body", "-", "--consequence", "every operator reads a wrong status",
            "--provenance", "witnessed — wrap-up, on abc1234",
            stdin="How it is reached:\n\n- a restart\n- any reload\n")
        assert code == 0, err
        assert out == "## Card it: the status line is wrong after every restart\n"
        b1 = entry_of(slice_dir, "B1")
        assert b1["restated"] == {
            "by": WU, "date": "2026-10-31",
            "headline": "Card it: the status line is wrong after every restart",
            "body": ["How it is reached:", "", "- a restart", "- any reload"],
            "consequence": "every operator reads a wrong status",
            "evidence": "witnessed", "author": "wrap-up, on abc1234"}
        # the author's own text is untouched
        assert b1["headline"] == "controller: the status line is wrong"
        assert b1["body"] == ["the body"] and b1["notes"][0]["by"] == "consult 1"
        code, out, err = run_cli("propose", slice_dir, "B1", "--by", WU, "--card", "--text",
                                 "Card it in KubeCoder, as the section says.",
                                 "--date", "2026-10-31")
        assert code == 0, err
        close_out.render_report(slice_dir)
        doc = report(slice_dir)
        # the section is the restatement, told once: no note, no author's text
        assert ("## Card it: the status line is wrong after every restart\n\n"
                "How it is reached:\n\n- a restart\n- any reload\n\n"
                "**Consequence:** every operator reads a wrong status\n\n"
                "**Provenance:** witnessed — wrap-up, on abc1234\n\n"
                "```decision id=B1\nproposal: Card it in KubeCoder, as the section says.\n"
                "```") in doc
        for gone in ("the body", "not owed as a phase", "controller: the status line"):
            assert gone not in doc, gone
        # the record keeps the trail under the heading the document asked it by
        record = (slice_dir / "close-out-record.md").read_text()
        assert ("### B1 — Card it: the status line is wrong after every restart · minor\n\n"
                "**As its author wrote it:** controller: the status line is wrong\n\n"
                "the body\n\n**Consequence:** an operator reads a wrong status\n\n"
                "**Provenance:** witnessed — code-reviewer, P3 r1\n\n"
                "**consult 1, 2026-10-31.** not owed as a phase\n\n"
                "**wrap-up, 2026-10-31.** asks for a card: Card it in KubeCoder, as the "
                "section says.") in record
        # the card an agreed card request files: the section's heading, then its body
        code, out, err = run_cli("show", slice_dir, "B1", "--card")
        assert code == 0, err
        assert out == ("Card it: the status line is wrong after every restart\n\n"
                       "How it is reached:\n\n- a restart\n- any reload\n\n"
                       "**Consequence:** every operator reads a wrong status\n\n"
                       "**Provenance:** witnessed — wrap-up, on abc1234\n")
        code, _, err = run_cli("show", slice_dir, "--card")
        assert code == 2 and "names the entries" in err
        # the full view shows both, the restatement first
        shown = close_out.show_view(slice_dir, ["B1"])
        assert shown.startswith(
            "### B1 — controller: the status line is wrong · minor\n\n"
            "**Restated** (wrap-up, 2026-10-31): Card it: the status line is wrong after "
            "every restart\n\nHow it is reached:")
        assert "**As its author wrote it:**\n\nthe body\n\n" in shown
        # a second restatement replaces the first, kept as history; the same again
        # adds nothing
        close_out.restate_entry(slice_dir, "B1", WU, "Card it: the status line",
                                "the new story", date="2026-11-01")
        b1 = entry_of(slice_dir, "B1")
        assert b1["restated"]["headline"] == "Card it: the status line"
        assert "consequence" not in b1["restated"]
        assert b1["notes"][-1] == {
            "by": WU, "date": "2026-11-01",
            "text": ["restatement replaced — was: Card it: the status line is wrong after "
                     "every restart", "", "How it is reached:", "", "- a restart",
                     "- any reload"], "history": "restated"}
        close_out.restate_entry(slice_dir, "B1", WU, "Card it: the status line",
                                "the new story", date="2026-11-02")
        assert len(entry_of(slice_dir, "B1")["notes"]) == len(b1["notes"])
        # the consequence and the provenance it does not give are the author's
        close_out.render_report(slice_dir)
        assert ("the new story\n\n**Consequence:** an operator reads a wrong status\n\n"
                "**Provenance:** witnessed — code-reviewer, P3 r1") in report(slice_dir)
        # refused: no headline, no body, a line cited by its number, a struck entry
        for argv, says in [
            (("--headline", " ", "--body", "b"), "needs --headline"),
            (("--headline", "h", "--body", " "), "needs --body"),
            (("--headline", "h", "--body", "see close_out.py:12"), "cites a line"),
            (("--headline", "h", "--body", "b", "--by", " "), "needs --by"),
        ]:
            code, _, err = run_cli(*restate, *argv)
            assert code == 2 and says in err, (argv, err)
        close_out.strike_entry(slice_dir, "B1", "gone")
        code, _, err = run_cli(*restate, "--headline", "h", "--body", "b")
        assert code == 2 and "B1 is struck" in err


def test_a_card_requests_section_is_at_most_the_trackers_card_length():
    """The card an agreed card request files is its section, so the section
    is at most `CARD_WORDS_MAX` words, heading and body counted: `propose
    --card` refuses a longer one, and so does a restatement of a card
    request; the detail stays in the record."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        run_cli("append", slice_dir, *DEFECT)                                    # B1
        long = " ".join(["word"] * close_out.CARD_WORDS_MAX)
        restated(slice_dir, "B1", body=long)
        code, _, err = run_cli("propose", slice_dir, "B1", "--by", WU, "--card",
                               "--text", "Card it, as this section says.")
        assert code == 2 and "B1's section is" in err and "at most 200" in err, err
        assert "the detail stays in the record" in err
        assert entry_of(slice_dir, "B1").get("wrap_up") is None
        # a section within the bound is the card request…
        restated(slice_dir, "B1", body="reached on every restart; the fix needs a design")
        code, _, err = run_cli("propose", slice_dir, "B1", "--by", WU, "--card",
                               "--text", "Card it, as this section says.")
        assert code == 0, err
        # …and a restatement of it is held to the same bound
        code, _, err = run_cli("restate", slice_dir, "B1", "--by", WU, "--headline",
                               "Card it", "--body", long)
        assert code == 2 and "B1's section is" in err, err
        assert entry_of(slice_dir, "B1")["restated"]["body"] == [
            "reached on every restart; the fix needs a design"]
        card = close_out.card_view(slice_dir, ["B1"])
        assert len(card.split()) <= close_out.CARD_WORDS_MAX


def test_a_proposal_is_one_line_of_at_most_the_bound():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        long = "Card it: " + "x" * close_out.asks.PROPOSAL_MAX
        code, _, err = run_cli("append", slice_dir, *with_flags(DEFECT, proposal=long))
        assert code == 2 and "a proposal is a line of at most 300" in err, err
        assert store(slice_dir)["entries"] == []
        run_cli("append", slice_dir, *DEFECT)                                    # B1
        code, _, err = run_cli("amend", slice_dir, "B1", "--proposal", long)
        assert code == 2 and "--proposal is" in err, err
        code, _, err = run_cli("propose", slice_dir, "B1", "--by", WU, "--text", long)
        assert code == 2 and "the proposal is" in err, err
        assert entry_of(slice_dir, "B1")["proposal"] is None
        # a proposal over several lines is collapsed into one, then bounded
        code, _, err = run_cli("propose", slice_dir, "B1", "--by", WU, "--text",
                               "Card it:\n  it needs a design.")
        assert code == 0, err
        assert entry_of(slice_dir, "B1")["proposal"] == "Card it: it needs a design."
        # the functions the loops call are not bounded
        close_out.propose_entry(slice_dir, "B1", "the run loop", long)
        assert entry_of(slice_dir, "B1")["proposal"] == long


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
                         "B7": "check", "B8": "note", "A1": "vet"}
        items = {e["id"]: a for e, a in close_out.worklist(slice_dir)}
        assert items["B2"] == "fold — fold it into slice 012"
        assert items["B6"] == "check — the trigger the close rests on"
        assert items["B7"] == "check — the signal the close rests on"
        code, out, _ = run_cli("worklist", slice_dir)
        lines = out.splitlines()
        assert lines[0] == "10 entries wait for the wrap-up"
        assert items["A1"] == ("vet — before the operator reads it: what a command settles, "
                               "a proposal where none, its vehicle")
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
        restated(slice_dir, "B5")
        close_out.propose_entry(slice_dir, "B5", "wrap-up", "more than the bar", mark="card")
        close_out.strike_entry(slice_dir, "B3", "fixed", commit="abc123")
        remaining = [e["id"] for e, _ in close_out.worklist(slice_dir)]
        assert remaining == ["B1", "B2", "B4", "I1", "B7", "B8", "A1"]
        # an entry the operator ruled on is theirs: it waits for nobody
        answer(slice_dir, "B4", answer="card it", by="pvginkel")
        remaining = [e["id"] for e, _ in close_out.worklist(slice_dir)]
        assert remaining == ["B1", "B2", "I1", "B7", "B8", "A1"]
        close_out.strike_entry(slice_dir, "B1", "x")
        for eid in ("B2", "I1", "B7", "B8", "A1"):
            close_out.leave_entry(slice_dir, eid, "w", "t")
        code, out, _ = run_cli("worklist", slice_dir)
        assert code == 0 and out.strip() == "nothing waits for the wrap-up"


RECHECK = ("recheck — a note came after the table closed it; check its labels against "
           "the note")
REVIEWER = "code-reviewer P15 r1"


def test_a_note_on_a_closed_entry_by_anyone_but_the_wrap_up_asks_a_recheck():
    """PilotApp slice 008: a reviewer's note on B16, which the table closed,
    said its labels were wrong, and the worklist never named it."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        closed = with_flags(DEFECT, trigger="fault", impact="degraded")
        for _ in range(7):
            run_cli("append", slice_dir, *closed)                                # B1–B7
        run_cli("append", slice_dir, *with_flags(DEFECT, trigger="fault"))       # B8
        assert [e["id"] for e, _ in close_out.worklist(slice_dir)] == ["B8"]
        assert close_out.table_route(entry_of(slice_dir, "B1"))[0] == "closed:fault"

        def asked():
            return {e["id"]: a for e, a in close_out.worklist(slice_dir)}

        def note(eid, by, text="its impact is wrong: the flow breaks"):
            assert run_cli("note", slice_dir, eid, "--by", by, "--text", text)[0] == 0

        def relabel(eid, by):
            code, _, err = run_cli("relabel", slice_dir, eid, "--by", by, "--note",
                                   "it says so itself", "--signal", "loud")
            assert code == 0, err

        note("B1", REVIEWER)
        # the wrap-up's own note, signed as it signs, asks nothing
        note("B2", "wrap-up")
        note("B2", "wrap-up, slice 022")
        # a relabel re-routed the entry already; a proposal replaced is history
        relabel("B3", REVIEWER)
        close_out.propose_entry(slice_dir, "B4", REVIEWER, "Card it.")
        close_out.propose_entry(slice_dir, "B4", REVIEWER, "Close it.")
        assert entry_of(slice_dir, "B4")["notes"][-1]["history"] == "proposal"
        # noted, then struck: settled
        note("B5", REVIEWER)
        close_out.strike_entry(slice_dir, "B5", "dup of B1")
        assert asked() == {"B1": RECHECK, "B8": "check — the trigger the close rests on"}
        # the existing check comes first
        note("B8", REVIEWER)
        assert asked()["B8"] == "check — the trigger the close rests on"
        code, out, _ = run_cli("worklist", slice_dir)
        assert f"B1 · {RECHECK}\n" in out
        # the wrap-up's leave takes it off; so does a relabel after the note
        note("B6", REVIEWER)
        note("B7", "close-out session")
        assert set(asked()) == {"B1", "B6", "B7", "B8"}
        close_out.leave_entry(slice_dir, "B1", "wrap-up", "the labels hold")
        relabel("B6", "wrap-up")
        assert set(asked()) == {"B7", "B8"}
        # a note after that relabel asks again
        note("B6", REVIEWER, "still loud?")
        assert asked()["B6"] == RECHECK


def test_a_for_folds_only_into_a_slice_still_unplanned_and_a_finished_one_drops_out():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp, later=("012_later_slice", "051_planned"))
        root = slice_dir.parent
        plan(root / "051_planned", how="plan")
        close_out.init_report(slice_dir)
        easy = with_flags(DEFECT, fix="one-edit", area="plain")
        run_cli("append", slice_dir, *with_flags(easy, **{"for": "12"}))           # B1
        run_cli("append", slice_dir, *with_flags(easy, **{"for": "51"}))           # B2
        assert [(e["id"], a.split(" — ")[0]) for e, a in close_out.worklist(slice_dir)] \
            == [("B1", "fold"), ("B2", "vet")]
        counts = close_out.entry_counts(slice_dir)
        assert (counts["to you"], counts["wrap-up"]) == (1, 1)
        assert route_of(slice_dir, "B2") == FOR_PLANNED
        assert route_of(slice_dir, "B1") == ("wrap-up:fold",
                                             "the wrap-up — fold into slice 012")
        # 012 runs and is completed: B1 goes where its other labels send it
        (root / "012_later_slice").rename(root / "completed" / "012_later_slice")
        assert [(e["id"], a.split(" — ")[0]) for e, a in close_out.worklist(slice_dir)] \
            == [("B1", "fix"), ("B2", "vet")]
        assert route_of(slice_dir, "B1") == ("wrap-up:fix", "the wrap-up — fix")
        assert FOR_PLANNED[1] in close_out.show_view(slice_dir, ["B2"])


# -- fold: an entry into a later slice's slice.md ------------------------------------

FOLD_SLICE = "018_dev_and_prd_stages"
PROSE = with_flags(DEFECT, kind="prose", headline="design/engine-and-sync.md names "
                   "the wrong table", body="line one\n\nline two", area=None,
                   fix="one-edit", repo="PilotAppSpecs")


def _fold_repo(tmp, git_init=True):
    """A spec repo with slice 018 reporting, an unplanned 011 in the backlog
    whose slice.md ends in blank lines, and the tree committed."""
    slice_dir = make_slice(tmp, name=FOLD_SLICE, later=("012_later_slice",))
    target = slice_dir.parent / "backlog" / "011_x" / "slice.md"
    target.parent.mkdir()
    target.write_text("# Slice 011\n\nthe ask\n\n\n")
    close_out.init_report(slice_dir)
    if git_init:
        git(slice_dir.parent.parent, "init", "-q")
        git(slice_dir.parent.parent, "add", ".")
        git(slice_dir.parent.parent, "commit", "-q", "--no-verify", "-m", "seed")
    return slice_dir, target


def _staged(spec):
    return subprocess.run(["git", "diff", "--cached", "--name-only"], cwd=spec,
                          check=True, capture_output=True, text=True).stdout.split()


def _fold(slice_dir, eid, *flags):
    return run_cli("fold", slice_dir / "close-out.md", eid, *flags)


def _fold_refused(slice_dir, eid, flags, *needles):
    spec = slice_dir.parent.parent
    before = {p: p.read_bytes() for p in spec.rglob("*") if p.is_file()
              and ".git" not in p.parts}
    code, out, err = _fold(slice_dir, eid, *flags)
    assert code == 2 and not out, (code, out, err)
    for needle in needles:
        assert needle in err, (needle, err)
    after = {p: p.read_bytes() for p in spec.rglob("*") if p.is_file()
             and ".git" not in p.parts}
    assert after == before
    return err


def _quoted(slice_dir, eid):
    return "\n".join(f"> {line}" if line else ">"
                     for line in close_out.show_view(slice_dir, [eid]).split("\n"))


def test_fold_appends_the_entry_verbatim_under_its_intro_and_stages_it():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, target = _fold_repo(tmp)
        spec = slice_dir.parent.parent
        assert run_cli("append", slice_dir, *with_flags(PROSE, **{"for": "11"}))[0] == 0
        files = _files(slice_dir)
        code, out, err = _fold(slice_dir, "P1", "--date", "2026-10-20")
        assert code == 0, err
        report_arg = slice_dir / "close-out.md"
        assert out == (
            "folded P1 into slices/backlog/011_x/slice.md (staged) — commit it, then: "
            f"close_out.py strike {report_arg} P1 --reason \"folded into slice 011\" "
            "--commit <sha> --by <you>\n")
        quoted = _quoted(slice_dir, "P1")
        assert target.read_text() == (
            "# Slice 011\n\nthe ask\n"
            "\n"
            "Slice 018's close-out, entry P1, verbatim (`close_out.py show`, 2026-10-20; "
            "report\n`slices/018_dev_and_prd_stages/close-out.md`):\n"
            "\n" + quoted + "\n")
        assert quoted.startswith("> ### P1 — design/engine-and-sync.md names the wrong "
                                 "table\n>\n> line one\n>\n> line two\n")
        assert quoted.endswith("> **Route:** the wrap-up — fold into slice 011")
        assert "> \n" not in target.read_text()
        assert _staged(spec) == ["slices/backlog/011_x/slice.md"]
        # neither the store nor the report is written: the strike is the caller's
        assert _files(slice_dir) == files
        assert entry_of(slice_dir, "P1")["strike"] is None
        # the printed strike works as printed, once the placeholders are filled
        code, _, err = run_cli("strike", report_arg, "P1", "--reason",
                               "folded into slice 011", "--commit", "abc123",
                               "--by", "wrap-up")
        assert code == 0, err


def test_fold_into_names_the_slice_for_an_entry_without_for_or_another_one():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, target = _fold_repo(tmp)
        spec = slice_dir.parent.parent
        backlog = slice_dir.parent / "backlog" / "031_in_the_backlog" / "slice.md"
        backlog.write_text("the ask\n")
        git(spec, "add", ".")
        git(spec, "commit", "-q", "--no-verify", "-m", "031")
        run_cli("append", slice_dir, *DEFECT)                                    # B1
        run_cli("append", slice_dir, *with_flags(PROSE, **{"for": "11"}))        # P1
        code, out, err = _fold(slice_dir, "B1", "--into", "031_in_the_backlog")
        assert code == 0, err
        assert out.startswith("folded B1 into slices/backlog/031_in_the_backlog/slice.md "
                              "(staged)")
        assert '--reason "folded into slice 031"' in out
        text = backlog.read_text()
        assert text.startswith("the ask\n\nSlice 018's close-out, entry B1, verbatim "
                               f"(`close_out.py show`, {close_out._today()}; report\n")
        assert text.endswith("\n\n" + _quoted(slice_dir, "B1") + "\n")
        # --into stands in for a `for` that names another slice
        code, out, err = _fold(slice_dir, "P1", "--into", "31")
        assert code == 0, err
        assert backlog.read_text().endswith(_quoted(slice_dir, "P1") + "\n")
        assert "entry P1" not in target.read_text()
        assert _staged(spec) == ["slices/backlog/031_in_the_backlog/slice.md"]


def test_fold_refuses_what_it_cannot_fold_and_writes_nothing():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, _ = _fold_repo(tmp)
        root = slice_dir.parent
        for name in ("051_planned", "052_seeded"):
            (root / "backlog" / name).mkdir()
            (root / "backlog" / name / "slice.md").write_text("the ask\n")
        plan(root / "backlog" / "051_planned")
        plan(root / "backlog" / "052_seeded", how="plan")
        run_cli("append", slice_dir, *DEFECT)                                    # B1
        run_cli("append", slice_dir, *with_flags(DEFECT, **{"for": "11"}))       # B2
        run_cli("strike", slice_dir, "B2", "--reason", "fixed in abc")
        run_cli("append", slice_dir, *with_flags(DEFECT, **{"for": "12"}))       # B3
        _fold_refused(slice_dir, "B1", [], "B1 has no `for` label", "--into")
        _fold_refused(slice_dir, "B2", [], "B2 is struck", "fixed in abc")
        _fold_refused(slice_dir, "B1", ["--into", "18"], "the report's own slice")
        _fold_refused(slice_dir, "B1", ["--into", "018_dev_and_prd_stages"],
                      "the report's own slice")
        # no folder at all: not created yet, and the entry is the operator's to hold
        _fold_refused(slice_dir, "B1", ["--into", "99"], "--into 99: slice 099 is not "
                      "created yet — the entry comes to the operator, to hold for that "
                      "slice")
        _fold_refused(slice_dir, "B1", ["--into", "2"],                  # completed since
                      "--into 2: no other slice still to run has that number")
        _fold_refused(slice_dir, "B1", ["--into", "next"], "--into next names no slice")
        for planned in ("51", "052"):               # a state.json, a seeded plan.md
            _fold_refused(slice_dir, "B1", ["--into", planned],
                          "is planned or running", "never reads slice.md again",
                          "add a phase or rule on its run")
        # the entry's own for, naming a folder without a slice.md
        _fold_refused(slice_dir, "B3", [], "slices/012_later_slice/slice.md does not "
                                           "exist")
        _fold_refused(slice_dir, "B9", ["--into", "11"], "no entry B9")
        _fold_refused(slice_dir, "B1", ["--into", "11", "--date", "20-10-2026"],
                      "is not YYYY-MM-DD")


def test_fold_refuses_an_entry_the_slice_md_holds_already_wherever_the_report_moved():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, target = _fold_repo(tmp)
        spec = slice_dir.parent.parent
        run_cli("append", slice_dir, *with_flags(PROSE, **{"for": "11"}))        # P1
        assert _fold(slice_dir, "P1", "--date", "2026-10-20")[0] == 0
        _fold_refused(slice_dir, "P1", [], "holds this fold already",
                      "slice 018's entry P1")
        # the slice is completed and its report moves: still the same fold
        git(spec, "commit", "-q", "--no-verify", "-m", "fold")
        moved = spec / "slices" / "completed" / FOLD_SLICE
        slice_dir.rename(moved)
        _fold_refused(moved, "P1", [], "holds this fold already")
        # the same id from another slice's report, or another id, is another fold
        assert close_out._folded_already(target.read_text(), "018", "P1", FOLD_SLICE)
        assert not close_out._folded_already(target.read_text(), "019", "P1", "019_other")
        assert not close_out._folded_already(target.read_text(), "018", "P2", FOLD_SLICE)


def test_fold_reports_a_staging_that_fails_and_leaves_the_fold():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir, target = _fold_repo(tmp, git_init=False)
        run_cli("append", slice_dir, *with_flags(PROSE, **{"for": "011_x"}))     # P1
        code, out, err = _fold(slice_dir, "P1")
        assert code == 2 and not out, (code, out, err)
        assert "folded P1 into slices/backlog/011_x/slice.md, but staging it failed" in err
        assert "git -C" in err and "add -- slices/backlog/011_x/slice.md" in err
        assert "The fold stays in slice.md, unstaged" in err
        assert "close_out.py strike" in err
        assert target.read_text().endswith(_quoted(slice_dir, "P1") + "\n")

        def hang(argv, **kw):
            raise subprocess.TimeoutExpired(argv, kw.get("timeout"))

        target.write_text("the ask\n")
        real = close_out.subprocess.run
        close_out.subprocess.run = hang
        try:
            code, _, err = _fold(slice_dir, "P1")
        finally:
            close_out.subprocess.run = real
        assert code == 2 and "did not answer within 30s" in err, err
        assert "entry P1" in target.read_text()


def test_fold_intro_wraps_at_100_without_breaking_a_backticked_span():
    short = close_out._fold_intro("7", "B1", "2026-10-20", "x/close-out.md")
    assert short == ("Slice 7's close-out, entry B1, verbatim (`close_out.py show`, "
                     "2026-10-20; report `x/close-out.md`):")
    for n in range(40):
        intro = close_out._fold_intro("0" * n + "18", "P1", "2026-10-20",
                                      "slices/completed/018_a-b_c/close-out.md")
        lines = intro.split("\n")
        assert all(len(line) <= 100 for line in lines), intro
        assert all(line.count("`") % 2 == 0 for line in lines), intro
        assert " ".join(lines) == close_out.FOLD_INTRO.format(
            own="0" * n + "18", eid="P1", date="2026-10-20",
            report="slices/completed/018_a-b_c/close-out.md")


def test_fold_is_in_the_verb_block_and_writes_no_store():
    assert close_out.verb_usage("fold").splitlines()[0] == (
        "close_out.py fold <close-out.md> <id> [--into SLICE] [--date DATE]")


# -- rule, the read-back, close ------------------------------------------------------


def _files(slice_dir):
    """The store and the two rendered files, as bytes; None for a file that is not
    there."""
    return tuple((slice_dir / name).read_bytes() if (slice_dir / name).exists() else None
                 for name in ("close-out.json", "close-out.md", "close-out-record.md"))


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
        close_out.render_report(slice_dir)
        assert "### ~~A1 — Settle V17 after" in (slice_dir / "close-out-record.md").read_text()


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


# -- render ----------------------------------------------------------------------

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
        text = (slice_dir / "close-out-record.md").read_text()
        assert "<not yet stamped>" not in text
        block = text[text.index("Run:"):]
        assert " ".join(block.split())[:len(header)] == header
        state = dict(STATE, cost={"cost_usd": 118.41, "planner_share": 0.18,
                                  "research_share": 0.04, "rework_share": 0.14})
        (slice_dir / "state.json").write_text(json.dumps(state))
        header = close_out.stamp_header(slice_dir)
        assert header.endswith("· $118.41 (planner 18 %, research 4 %, rework 14 %)")
        record = (slice_dir / "close-out-record.md").read_text()
        assert record.count("Run:") == 1
        # wrapped at the report's width
        assert all(len(line) <= close_out.HEADER_WIDTH for line in record.splitlines())
        # the document carries the run in its context, once there is an ask
        run_cli("append", slice_dir, *ACTION)
        close_out.render_report(slice_dir)
        assert ("**The run.** 2026-08-14 19:49 → 23:53 · 11 phases (8 planned, P9, P10, "
                "P11 appended) · 2 bail-outs · 1 test round · doc phase done · $118.41 "
                "(planner 18 %, research 4 %, rework 14 %).") in report(slice_dir)


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
        assert places(slice_dir) == {"For the wrap-up": ["B1"]}
        (slice_dir / "state.json").write_text(json.dumps(STATE))
        assert route_of(slice_dir, "B1") == (
            "card:table", "card request — the fix lives in HelmCharts, which the slice "
                          "did not touch")
        # with no proposal of its own, the document proposes the card the route asks for
        close_out.render_report(slice_dir)
        assert ("```decision id=B1\nproposal: \"Card it for HelmCharts: the fix lives "
                "there, and this slice did not touch it.\"\n```") in report(slice_dir)


# -- init, counts, list ------------------------------------------------------------

def test_init_creates_the_store_once_and_renders_it():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        code, out, _ = run_cli("init", slice_dir / "close-out.md")
        assert code == 0 and out.startswith("created ")
        assert sorted(p.name for p in slice_dir.iterdir()) == ["close-out.json"]
        assert store(slice_dir) == {"store": 2, "slice": "007_argocd_tools_presync_hook",
                                    "closed": None, "entries": []}
        run_cli("append", slice_dir, *DEFECT)
        assert close_out.init_report(slice_dir) is False
        assert len(store(slice_dir)["entries"]) == 1
        code, out, _ = run_cli("init", slice_dir)
        assert code == 0 and out.startswith("exists ")
        code, _, err = run_cli("list", Path(tmp) / "nowhere")
        assert code == 2 and "not found" in err


def test_counts_live_entries_per_section_and_per_letter_on_one_line():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        assert close_out.counts_line(close_out.entry_counts(slice_dir)) == (
            "to you 0 · card requests 0 · wrap-up 0 · unlabelled 0 · closed 0 · "
            "record 0 "
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
        assert close_out.counts_line(close_out.entry_counts(slice_dir)) == (
            "to you 1 · card requests 0 · wrap-up 1 · unlabelled 1 · closed 1 · "
            "record 1 "
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
        restated(slice_dir, "B1")
        close_out.propose_entry(slice_dir, "B1", "wrap-up", "needs a design", mark="card")
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
        answer(slice_dir, "A1", answer="do it", by="pvginkel")
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
            "**Route:** closed — the wrap-up looked and left it")
        assert "**Proposal:**" not in b1
        assert a1.startswith(
            "controller: the status line is wrong\n\nthe body\n\n"
            "**Proposal:** Do it before the next run: one command.\n\n"
            "**Consequence:** an operator reads a wrong status\n\n"
            "**Triage:** action · shows on an ordinary condition · breaks a flow · silent\n"
            "**Provenance:** witnessed — code-reviewer, P3 r1\n"
            "**Route:** to you — an action\n**Ruling:** answer: do it · by pvginkel")
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
                           "its store,\nclose-out.json, once, at the run's end. Write to it "
                           f"only through `python3 {tool}\n<verb> {report_md} …` —")
    assert ("`append`, `note`, `strike`, and `amend <id>`, which\ncorrects an entry "
            "(any of `append`'s flags but --kind, each replacing its\nfield); `list` "
            "shows what is there") in line
    assert ("— never where the entry goes. "
            f"`python3 {tool} labels` prints\nwhat each label means —") in line
    assert ("The labels each\nkind carries, every one of them, `unknown` where you "
            "cannot tell:\n" + close_out.kind_labels_text() + "\n" + close_out.LABEL_PAIRING
            + "\nThe verbs take:\n" + close_out.verb_usage("append", "note", "strike")
            + "\nThe report is about the work;") in line
    # every verb the line names to write with has its arguments in it
    for verb in ("append", "note", "strike"):
        assert f"close_out.py {verb} <close-out.md>" in line, verb
    assert "close_out.py note <close-out.md> <id> --by BY --text TEXT" in line
    assert "--reason REASON [--by BY]" in line
    assert "unnote" not in line and "unstrike" not in line
    assert line.endswith("goes to the `fieldnotes` MCP tool\n`post` instead.")


def test_dispatch_line_without_relabel_does_not_offer_it():
    report_md = "/specs/slices/007_x/close-out.md"
    line = close_out.dispatch_line(report_md)
    assert close_out.dispatch_line(report_md, relabel=False) == line
    assert "field); `list` shows what is there" in line
    assert "`relabel <id>" not in line and "close_out.py relabel" not in line


def test_dispatch_line_with_relabel_offers_it_and_its_arguments():
    report_md = "/specs/slices/007_x/close-out.md"
    line = close_out.dispatch_line(report_md, relabel=True)
    assert ("field); `relabel <id> --by <who> --note\n"
            "<what you found>` corrects an entry's labels where you can show they are\n"
            "wrong, whoever appended it: the tool routes an entry from its labels,\n"
            "never from a note; `list` shows what is there") in line
    assert ("\nThe verbs take:\n"
            + close_out.verb_usage("append", "note", "strike", "relabel")
            + "\nThe report is about the work;") in line
    assert "close_out.py relabel <close-out.md> <id> --by BY --note NOTE" in line
    # the rest is the line without it
    assert line.replace(close_out.DISPATCH_RELABEL, "", 1).replace(
        "\n" + close_out.verb_usage("relabel"), "", 1) == close_out.dispatch_line(report_md)


def test_verb_usage_renders_append_compactly_with_its_help_strings():
    block = close_out.verb_usage("append")
    lines = block.splitlines()
    assert lines[0].startswith("close_out.py append <close-out.md> --kind {action,decision,"
                               "event,defect,prose,test-gap,improvement} --headline HEADLINE")
    assert " [-h]" not in block
    assert "--section" not in block
    assert "[--repo NAME]" in lines[0] and "[--for SLICE]" in lines[0]
    assert "[--product-call {yes,no}]" in lines[0]
    assert ("--consequence CONSEQUENCE [--proposal PROPOSAL] [--option LABEL [LINE ...]] "
            "[--recommend LABEL] [--check CHECK] [--due {merge,test,push,close}] "
            "[--provenance") in lines[0]
    assert len(lines) == 1 + 25
    for flag, help_ in (
            ("--kind", "what the entry is — it decides which of the labels below the "
                       "entry carries"),
            ("--body", "entry body, or - for stdin"),
            ("--proposal", "what you would do about it and why, in a sentence or two, in "
                           "a ruling's words (card · fix now · fold into <slice> · close · "
                           "do it), one line of at most 300 characters — the operator "
                           "reads it with the headline and the Consequence; required for "
                           "an action and an improvement, refused on a decision"),
            ("--option", "a decision's option, or an answer an action asks "
                                    "for: the label, then one line saying what it is or "
                                    "costs; repeat it for each — a decision puts two or "
                                    "more"),
            ("--recommend", "a decision: the label of the option you would pick — "
                            "required for a decision, in place of --proposal"),
            ("--check", "an action: the fact that shows it done — `env <NAME>`, `file "
                        "<repo>:<path>`, `origin <repo> <branch>:<path> contains <text>`, "
                        "`slice <NNN> completed`, or `manual` where none captures it; "
                        "repeat it for each fact. Never a commit or an environment. An "
                        "action owed before the run needs one"),
            ("--due", "what must not happen before the entry is dealt with: the phase's "
                      "merge, the test phase, the push, or the report's close"),
            ("--by", "who appends — role, phase and round"),
            ("--for", "the number of another slice that should take the entry — one "
                      "still to run, or one the plan names that triage has not created "
                      "yet, for which the operator is asked to hold it — never the slice "
                      "being run; leave it out for an entry about this one. One already "
                      "planned or running brings the entry to the operator, since that "
                      "run never reads slice.md"),
            ("--prevents", "improvement: the worst it would prevent")):
        assert f"    {flag}: {help_}" in lines, flag
    wrap_up = close_out.verb_usage("show", "restate", "propose").splitlines()
    assert wrap_up[0] == "close_out.py show <close-out.md> [<id> ...] [--card]"
    assert ("close_out.py restate <close-out.md> <id> --by BY --headline HEADLINE "
            "--body BODY [--consequence CONSEQUENCE] [--provenance PROVENANCE] "
            "[--date DATE]") in wrap_up
    assert ("close_out.py propose <close-out.md> <id> --by BY --text TEXT "
            "[--card | --word] [--date DATE]") in wrap_up
    for help_ in ("    --by: who proposes",
                  "    --text: what Agree does, in a ruling's words, one line of at most "
                  "300 characters, or - for stdin",
                  "    --card: the wrap-up asks for a card, the entry restated as the card; "
                  "it becomes a card request",
                  "    --headline: the section's heading: the ask, as the operator reads it"):
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
    assert close_out.verb_usage("rule").splitlines()[0] == (
        "close_out.py rule <close-out.md> <id> --did DID [--commit COMMIT] [--date DATE]")
    assert close_out.verb_usage("note").splitlines()[0].startswith(
        "close_out.py note <close-out.md> <id> --by BY --text TEXT")
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
    skeleton = re.search(r"^```markdown\n(# Close-out record.*?)^```", doc,
                         re.S | re.M).group(1)
    assert re.findall(r"^## (.+)$", skeleton, re.M) == list(close_out.RECORD_SECTIONS)
    verbs_doc = doc[doc.index("## The verbs"):]
    in_doc = re.findall(r"^\| `([a-z-]+)` \|", verbs_doc, re.M)
    _, subs = close_out.build_parser()
    assert sorted(in_doc) == sorted(subs)


def test_slice_dir_of_accepts_the_directory_the_report_or_the_store():
    assert close_out.slice_dir_of("/s/007_x") == Path("/s/007_x")
    assert close_out.slice_dir_of("/s/007_x/close-out.md") == Path("/s/007_x")
    assert close_out.slice_dir_of("/s/007_x/close-out.json") == Path("/s/007_x")


def places(slice_dir):
    """The ids in each place of the report that holds any, as the render puts them."""
    data = close_out._read_store(slice_dir)
    return {place: [e["id"] for e, _, _ in items]
            for place, items in close_out._placed(data, slice_dir) if items}


def route_of(slice_dir, eid):
    return close_out.route(entry_of(slice_dir, eid), close_out.touched_repos(slice_dir),
                           close_out.slice_stages(slice_dir))


def test_relabel_for_none_clears_for():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        run_cli("append", slice_dir, *with_flags(DEFECT, **{"for": "12"}))
        relabel = ("relabel", slice_dir, "B1", "--by", "wrap-up", "--date", "2026-10-14")
        code, out, err = run_cli(*relabel, "--note", "it is this slice's", "--for", "none")
        assert code == 0, err
        assert out.strip() == ("wrap-up, 2026-10-14 — relabelled (for: 012 → —): it is "
                               "this slice's")
        e = entry_of(slice_dir, "B1")
        assert "for" not in e["labels"]
        assert e["notes"][-1]["relabel"] == {"for": ["012", None]}
        assert route_of(slice_dir, "B1")[0] != "wrap-up:fold"
        # nothing left to clear: a relabel that changes nothing
        code, _, err = run_cli(*relabel, "--note", "n", "--for", "NONE")
        assert code == 2 and "changes nothing" in err
        try:
            close_out.relabel_entry(slice_dir, "B1", "w", "n", labels={"for": "none"})
            raise AssertionError("clearing a `for` the entry lacks must raise")
        except ReportError as e:
            assert "changes nothing" in str(e)


def answer(slice_dir, eid, **lines):
    """Pilot's answer lines on one entry, read back as `absorb` reads them."""
    with close_out._writing(slice_dir) as data:
        return close_out._absorb(data, {eid: {"lines": lines}}, "2026-10-30")


def test_a_write_that_fails_leaves_the_store_as_it_was():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        run_cli("append", slice_dir, *DEFECT)                                    # B1
        before = _files(slice_dir)
        code, _, err = run_cli("note", slice_dir, "B9", "--by", "op", "--text", "t")
        assert code == 2 and "no entry B9" in err
        code, _, err = run_cli("append", slice_dir, *with_flags(DEFECT, impact="none"))
        assert code == 2
        assert _files(slice_dir) == before


def _every_place(tmp):
    """A slice whose report holds an entry in every place, by every way in."""
    slice_dir = make_slice(tmp, later=("012_later_slice", "051_planned"))
    plan(slice_dir.parent / "051_planned")
    (slice_dir / "state.json").write_text(json.dumps(STATE))
    (slice_dir / "plan.md").write_text(
        "# Plan\n\n### P1 — the hook ✅ DONE 2026-08-14\n\nTarget: app\n\n"
        "### P2 — the docs\n\nTarget: app\n")
    close_out.init_report(slice_dir)
    run_cli("append", slice_dir, *ACTION, "--check", "file deploy:jobs/nightly.yaml",
            "--due", "push", "--option", "Done", "--option", "Not possible",
            "say why")                                                          # A1
    run_cli("append", slice_dir, *DECISION)                                     # D1
    run_cli("append", slice_dir, *with_flags(DEFECT, trigger="fault", impact="severe",
                                             proposal="Card it: it needs a design."))  # B1
    run_cli("append", slice_dir, *with_flags(DEFECT, repo="HelmCharts"))        # B2
    run_cli("append", slice_dir, *with_flags(EASY, body="## the page\n\n```\n# k\n```"))
    restated(slice_dir, "B3", headline="edit the page, on your word",
             body="## the page, as it would be\n\n```\n# k\n```\n\nthe rule that reserves it",
             date="2026-08-14")
    close_out.propose_entry(slice_dir, "B3", "wrap-up", "edit the page; a rule reserves it",
                            date="2026-08-14", mark="word")                     # B3
    run_cli("append", slice_dir, *with_flags(DEFECT, **{"for": "77"}))          # B4
    run_cli("append", slice_dir, *with_flags(DEFECT, **{"for": "51"}))          # B5
    run_cli("append", slice_dir, *DEFECT)                                       # B6
    close_out.append_entry(slice_dir, "defect", "unlabelled", "b", consequence="c")  # B7
    run_cli("append", slice_dir, *with_flags(DEFECT, trigger="fault"))          # B8
    close_out.append_entry(slice_dir, "event", "resumed", "b", consequence="none")  # E1
    run_cli("append", slice_dir, *EASY)                                         # B9
    close_out.strike_entry(slice_dir, "B9", "fixed", by="wrap-up", commit="abc1234")
    close_out.add_note(slice_dir, "B6", "consult 1", "still true", date="2026-08-14")
    return slice_dir


def test_render_writes_the_asks_as_the_document_pilot_reads():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = _every_place(tmp)
        said = close_out.render_report(slice_dir, step="T7")
        assert said == "close-out-record.md and close-out.md written: 9 asks"
        doc = report(slice_dir)
        asks = close_out.asks
        blocks = asks.read_back(doc)
        assert {bid: b["kind"] for bid, b in blocks.items()} == {
            "A1": "action", "D1": "decision", "B1": "decision", "B3": "decision",
            "B4": "decision", "B5": "decision", "B2": "decision", "B6": "question",
            "B7": "question"}
        assert all(not b["lines"] for b in blocks.values())
        # what comes to the operator, then the card requests, then what no wrap-up
        # reached, then what nobody routed — each by grade, kind and id
        heads = re.findall(r"^## (.+)$", doc, re.M)
        assert len(heads) == 9
        assert doc.startswith(
            "---\ntitle: Close-out of slice 007 — argocd tools presync hook\n"
            "summary: \"Slice 007's close-out: what is yours to rule or to do, the cards "
            "asked for, what no wrap-up reached and what nobody routed\"\nstep: T7\n---\n")
        assert ("**The run.** 2026-08-14 19:49 → 23:53 · 11 phases (8 planned, P9, P10, "
                "P11 appended) · 2 bail-outs · 1 test round · doc phase done.") in doc
        assert "**What shipped.** P1 the hook." in doc
        assert "**The wrap-up** fixed B9, a commit each." in doc
        # the blocks, each as its kind takes it
        assert ("```action id=A1\noptions:\n  - Done\n  - Not possible: say why\n"
                "check: file deploy:jobs/nightly.yaml\n```") in doc
        assert ("```decision id=D1\noptions:\n  - Keep it: nothing changes\n"
                "  - Change it: costs a release\nrecommend: Keep it\n```") in doc
        assert "```decision id=B1\nproposal: \"Card it: it needs a design.\"\n```" in doc
        assert ("```decision id=B4\nproposal: Hold it for slice 077, which is not created "
                "yet.\n```") in doc
        assert ("```decision id=B5\nproposal: Add a phase to slice 051's plan, or rule on "
                "its run.\n```") in doc
        assert "```question id=B7\n```" in doc
        # the prose above each block: an action's proposal, the consequence, the
        # provenance; no note, no route, no grade, no labels
        assert ("**Proposal:** Do it before the next run: one command.\n\n**Consequence:** "
                "an operator reads a wrong status\n\n**Provenance:** witnessed — "
                "code-reviewer, P3 r1\n\n```action id=A1") in doc
        assert "still true" not in doc
        # a restated entry's section is its restatement, a heading in its text
        # escaped and one inside a fence left alone
        assert ("## edit the page, on your word\n\n\\## the page, as it would be\n\n```\n"
                "# k\n```\n\nthe rule that reserves it\n\n**Consequence:** an operator "
                "reads a wrong status\n\n**Provenance:** witnessed — code-reviewer, P3 r1"
                "\n\n```decision id=B3\nproposal: edit the page; a rule reserves it\n```"
                ) in doc
        assert "**Not reached.** The table gave this entry to the wrap-up" in doc
        assert "**Unlabelled.** The entry carries no labels" in doc
        assert "**For slice 077**, which no folder holds yet." in doc
        for gone in ("**Route:**", "**Triage:**", "**Disposition:**", " · minor",
                     "**Latest**", "due"):
            assert gone not in doc, gone
        # the document is one Pilot takes: the store it came from has no fault
        assert asks.problems(close_out._document(close_out._read_store(slice_dir),
                                                 slice_dir)) == []
        # the record holds what the document leaves out
        record = (slice_dir / "close-out-record.md").read_text()
        assert record.startswith("# Close-out record — slice 007 argocd tools presync hook"
                                 "\n\nRun: 2026-08-14 19:49 → 23:53")
        assert re.findall(r"^## (.+)$", record, re.M) == ["Asked", "Closed", "Record"]
        # what the document asks, with the trail its section leaves out: the
        # author's own text where a restatement took its place, every note, the
        # wrap-up's mark
        asked = record[record.index("## Asked"):record.index("## Closed")]
        assert ("### B3 — edit the page, on your word\n\n**As its author wrote it:** "
                "controller: the status line is wrong\n\n\\## the page\n\n```\n# k\n```"
                "\n\n**Consequence:** an operator reads a wrong status") in asked
        assert ("**wrap-up, 2026-08-14.** asks for the operator's word: edit the page; a "
                "rule reserves it") in asked
        assert ("### B6 — controller: the status line is wrong\n\n**consult 1, "
                "2026-08-14.** still true") in asked
        assert "### D1 — " in asked and "### A1 — " in asked
        closed = record[record.index("## Closed"):record.index("## Record")]
        assert "### B8 — controller: the status line is wrong" in closed
        assert "**Route:** closed — it needs a fault" in closed
        assert ("### ~~B9 — controller: the status line is wrong~~ — fixed (abc1234); "
                "struck by wrap-up") in record
        assert "### E1 — resumed" in record
        # rendering again changes nothing
        before = _files(slice_dir)
        close_out.render_report(slice_dir)
        assert _files(slice_dir) == before
        assert store(slice_dir)["step"] == "T7"


def test_render_leaves_a_written_back_document_and_removes_one_left_with_no_ask():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        assert close_out.render_report(slice_dir) == \
            "close-out-record.md written; nothing to ask, so no close-out.md"
        assert not (slice_dir / "close-out.md").exists()
        run_cli("append", slice_dir, *ACTION)
        close_out.render_report(slice_dir)
        assert (slice_dir / "close-out.md").exists()
        close_out.strike_entry(slice_dir, "A1", "done after all")
        close_out.render_report(slice_dir)
        assert not (slice_dir / "close-out.md").exists()
        run_cli("append", slice_dir, *ACTION)                                    # A2
        close_out.render_report(slice_dir)
        written = report(slice_dir).replace("```action id=A2\n",
                                            "```action id=A2\ndone: 2026-10-30T12:00:00Z\n")
        (slice_dir / "close-out.md").write_text(written)
        run_cli("append", slice_dir, *DEFECT)
        assert close_out.render_report(slice_dir) == (
            "close-out-record.md written; close-out.md left as Pilot wrote it back "
            "(answers on A2): `absorb` reads it")
        assert report(slice_dir) == written
        # a store Pilot would refuse is refused, naming the entry, the record written
        data = store(slice_dir)
        data["entries"][-1]["headline"] = "ends in a mark #"
        (slice_dir / "close-out.json").write_text(json.dumps(data))
        (slice_dir / "close-out.md").unlink()
        try:
            close_out.render_report(slice_dir)
            raise AssertionError("a heading Pilot reads otherwise must raise")
        except ReportError as e:
            assert "ask B1: the headline ends in `#`" in str(e) and "`amend`" in str(e)


def _answered(slice_dir, **answers):
    """close-out.md with Pilot's answer lines written into the blocks named."""
    text = report(slice_dir)
    for bid, lines in answers.items():
        at = re.search(rf"^```\w+ id={bid}\n", text, re.M).end()
        end = text.index("```", at)
        text = text[:end] + lines + text[end:]
    (slice_dir / "close-out.md").write_text(text)


def test_absorb_reads_the_answers_back_into_rulings_the_continuation_carries_out():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = _every_place(tmp)
        close_out.render_report(slice_dir)
        _answered(slice_dir,
                  A1="done: 2026-10-30T12:00:00Z\nby: pvginkel\nnote: created by hand\n",
                  D1="answer: Change it\nby: pvginkel\nat: 2026-10-30T12:00:00Z\n"
                     "via: app\n",
                  B1="answer: Agree\nby: agent\nnote: |\n  small, and the design is "
                     "known\n",
                  B4="answer: deferred\nto: T9\nat: 2026-10-30T12:00:00Z\n",
                  B2="answer: \"card it: in HelmCharts\"\nby: pvginkel\n")
        code, out, err = run_cli("absorb", slice_dir, "--date", "2026-10-30")
        assert code == 0, err
        assert out.splitlines() == [
            "A1  done by pvginkel", "D1  answered by pvginkel: Change it",
            "B1  answered by agent: Agree", "B3  open", "B4  deferred to T9 by agent",
            "B5  open", "B2  answered by pvginkel: card it: in HelmCharts", "B6  open",
            "B7  open"]
        d1 = entry_of(slice_dir, "D1")
        assert d1["ruling"] == {"answer_lines": {"answer": "Change it", "by": "pvginkel",
                                                 "at": "2026-10-30T12:00:00Z",
                                                 "via": "app"},
                                "did": None, "date": "2026-10-30"}
        assert d1["strike"] is None
        # done and deferred close themselves; Pilot's own choice is said as Pilot's
        a1 = entry_of(slice_dir, "A1")
        assert a1["ruling"]["did"] == "created by hand"
        assert a1["strike"]["reason"] == "done by pvginkel: created by hand"
        b4 = entry_of(slice_dir, "B4")
        assert b4["strike"] == {"reason": "deferred to T9 by Pilot", "by": "Pilot",
                                "date": "2026-10-30", "commit": None}
        # an entry ruled on waits for no wrap-up, and close keeps one not carried out
        assert "B2" not in [e["id"] for e, _ in close_out.worklist(slice_dir)]
        code, out, _ = run_cli("close", slice_dir, "--by", "run-slice")
        assert out.strip() == ("6 entries closed; the report stays open over D1, B1, B2, "
                               "ruled and not carried out")
        assert store(slice_dir)["closed"] is None
        # the continuation records what it did, which strikes the entry
        code, out, err = run_cli("rule", slice_dir, "B1", "--did", "carded as P-130")
        assert code == 0, err
        assert out.strip() == ("B1: answer: Agree · note: small, and the design is known · "
                               "chosen by Pilot; the operator did not decide this — carded "
                               "as P-130")
        assert entry_of(slice_dir, "B1")["strike"]["by"] == "Pilot's ruling"
        close_out.rule_entry(slice_dir, "D1", "kept the design open", commit="def5678")
        close_out.rule_entry(slice_dir, "B2", "carded as KC-12")
        assert entry_of(slice_dir, "D1")["strike"] == {
            "reason": "kept the design open", "by": "the operator's ruling",
            "date": close_out._today(), "commit": "def5678"}
        for eid, did, needle in (("B6", "x", "B6 holds no ruling to act on"),
                                 ("B1", "y", "B1 is done already"),
                                 ("B1", " ", "--did is empty")):
            code, _, err = run_cli("rule", slice_dir, eid, "--did", did)
            assert code == 2 and needle in err, err
        n, stay = close_out.close_report(slice_dir, by="run-slice", date="2026-10-30")
        assert (n, stay) == (0, [])
        assert store(slice_dir)["closed"] == {"date": "2026-10-30", "by": "run-slice"}
        # the final render writes the record under the answered asks, verbatim
        close_out.render_report(slice_dir)
        record = (slice_dir / "close-out-record.md").read_text()
        assert "\n\nClosed: 2026-10-30 — by run-slice\n\n## Ruled\n" in record
        ruled = record[record.index("## Ruled"):record.index("## Record")]
        assert re.findall(r"^### ~~(\w+)", ruled, re.M) == ["A1", "B1", "B2", "B4", "D1"]
        assert ("**Ruling:** answer: Change it · by pvginkel via app · at "
                "2026-10-30T12:00:00Z — kept the design open") in ruled
        assert "**Ruling:** answer: deferred · to: T9 · chosen by Pilot" in ruled
        assert "## Asked" not in record


def test_absorb_refuses_a_document_not_the_stores_and_an_undo_reopens_the_ask():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        run_cli("append", slice_dir, *ACTION)
        code, _, err = run_cli("absorb", slice_dir)
        assert code == 2 and "close-out.md cannot be read" in err
        close_out.render_report(slice_dir)
        text = report(slice_dir)
        (slice_dir / "close-out.md").write_text(text.replace("id=A1", "id=A9"))
        before = _files(slice_dir)
        code, _, err = run_cli("absorb", slice_dir)
        assert code == 2 and "block A9, which no entry of the store is" in err, err
        assert _files(slice_dir) == before
        (slice_dir / "close-out.md").write_text(text.replace("```action", "```Action"))
        code, _, err = run_cli("absorb", slice_dir)
        assert code == 2 and "is a fault to Pilot" in err, err
        # an answer, then its Undo: the ruling nobody carried out goes again
        (slice_dir / "close-out.md").write_text(
            text.replace("```action id=A1\n", "```action id=A1\nanswer: later\nby: op\n"))
        assert close_out.absorb_report(slice_dir) == ["A1  answered by op: later"]
        (slice_dir / "close-out.md").write_text(text)
        assert close_out.absorb_report(slice_dir) == ["A1  open"]
        assert entry_of(slice_dir, "A1")["ruling"] is None


def test_owed_before_push_and_before_the_test_phase_read_the_due_an_author_set():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        (slice_dir / "verification.json").write_text(json.dumps(
            {"items": [{"id": "V01"}, {"id": "V15"}]}))
        close_out.init_report(slice_dir)
        run_cli("append", slice_dir, *with_flags(DEFECT, due="push"))              # B1
        run_cli("append", slice_dir, *with_flags(DEFECT, kind="prose", area=None,
                                                 due="test",
                                                 headline="V15 is worded against D2, "
                                                          "and V1 too"))          # P1
        run_cli("append", slice_dir, *with_flags(DEFECT, due="test",
                                                 headline="no criterion named"))  # B2
        run_cli("append", slice_dir, *with_flags(DEFECT, trigger="fault",
                                                 impact="severe"))                # B3
        run_cli("append", slice_dir, *with_flags(DEFECT, proposal="Fix it before the "
                                                                  "push."))       # B4
        push = [(e["id"], r) for e, r in close_out.owed_before_push(slice_dir)]
        assert push == [("B1", ["due before the push"]), ("B3", ["impact severe"])]
        test = [(e["id"], r) for e, r in close_out.owed_before_test(slice_dir)]
        assert test == [("B2", ["due before the test phase"]), ("P1", ["V01", "V15"])]
        close_out.strike_entry(slice_dir, "B1", "fixed")
        assert [e["id"] for e, _ in close_out.owed_before_push(slice_dir)] == ["B3"]


def test_the_record_show_and_document_escape_an_authors_less_than_outside_code():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        code, _, err = run_cli("append", slice_dir, *with_flags(
            ACTION, headline="controller: the <time> line is wrong",
            body="It shows `<time>` raw and <time> after.",
            proposal="Fix the <time> line: `fmt(<time>)`."))
        assert code == 0, err
        code, _, err = run_cli(
            "append", slice_dir,
            *with_flags(ACTION, kind="decision", proposal=None,
                        headline="which <tag> the line keeps"),
            "--option", "Keep <it>", "nothing changes", "--option", "Change it",
            "costs a release", "--recommend", "Keep <it>")
        assert code == 0, err
        close_out.render_report(slice_dir)
        record = (slice_dir / "close-out-record.md").read_text()
        assert "A1 — controller: the \\<time> line is wrong" in record
        assert "D1 — which \\<tag> the line keeps" in record
        assert "Run: \\<not yet stamped>" in record
        assert "<" not in record.replace("\\<", "")
        document = report(slice_dir)
        for line in ("## controller: the \\<time> line is wrong",
                     "It shows `<time>` raw and \\<time> after.",
                     "**Proposal:** Fix the \\<time> line: `fmt(<time>)`.",
                     "## which \\<tag> the line keeps",
                     "  - Keep <it>: nothing changes", "recommend: Keep <it>"):
            assert f"\n{line}\n" in document, line
        shown = close_out.show_view(slice_dir, ["A1", "D1"])
        assert "It shows `<time>` raw and \\<time> after." in shown
        assert "- **Keep \\<it>** (recommended): nothing changes" in shown


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
