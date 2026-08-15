"""Tests for close_out — the close-out report's mechanics.

A throwaway slice folder per test; the template is read from the plugin's
own docs (so a template edit that breaks the lift fails here). Stdlib only;
runs standalone and under pytest.

Run: `python3 ${CLAUDE_PLUGIN_ROOT}/tools/test_close_out.py` or via pytest.
"""

import contextlib
import importlib.util
import io
import json
import re
import tempfile
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "close_out", Path(__file__).resolve().parent / "close_out.py"
)
close_out = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(close_out)
ReportError = close_out.ReportError


def make_slice(tmp, name="007_argocd_tools_presync_hook"):
    slice_dir = Path(tmp) / "specs" / "slices" / name
    slice_dir.mkdir(parents=True)
    return slice_dir


def report(slice_dir):
    return (slice_dir / "close-out.md").read_text()


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
    "phases": {},
}


# -- init -------------------------------------------------------------------

def test_init_creates_from_template_with_the_slice_in_the_title():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        assert close_out.init_report(slice_dir) is True
        text = report(slice_dir)
        assert text.startswith("# Close-out — slice 007 argocd_tools_presync_hook\n")
        assert "Run: <not yet stamped>" in text
        for section in close_out.SECTIONS:
            assert f"\n## {section}\n" in text
        assert "\n## Summary\n" in text
        # The template's own placeholder title never leaks through.
        assert "NNN <slug>" not in text


def test_init_never_touches_an_existing_report():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        (slice_dir / "close-out.md").write_text("# hand-written\n")
        assert close_out.init_report(slice_dir) is False
        assert report(slice_dir) == "# hand-written\n"


def test_template_doc_opens_with_the_skeleton():
    body = close_out.template_body()
    assert body.startswith(close_out.TEMPLATE_TITLE)
    headings = re.findall(r"^## (.+)$", body, re.M)
    assert headings == ["Summary", *close_out.SECTIONS]


# -- append -----------------------------------------------------------------

def test_append_allocates_ids_per_section_in_the_entry_shape():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        b1 = close_out.append_entry(
            slice_dir, "Bugs", "presync exits with a traceback",
            "`kubeconfig.identity()` checks that `ca.crt` exists but not that "
            "it parses.\n\nExit is still non-zero.",
            provenance="P3 review r1 F3 (advisory)", severity="minor")
        n1 = close_out.append_entry(
            slice_dir, "Notable events", "P3 bailed blocked", "venue off the wire")
        b2 = close_out.append_entry(
            slice_dir, "Bugs", "second bug", "body")
        assert (b1, n1, b2) == ("B1", "N1", "B2")
        text = report(slice_dir)
        assert ("### B1 — presync exits with a traceback · minor\n\n"
                "`kubeconfig.identity()` checks that `ca.crt` exists but not that "
                "it parses.\n\nExit is still non-zero.\n\n"
                "Provenance: P3 review r1 F3 (advisory)\nDisposition:\n") in text
        # An entry without provenance still carries the operator's line.
        assert "### N1 — P3 bailed blocked\n\nvenue off the wire\n\nDisposition:\n" in text
        # Entries land in their own section, before the next heading, and
        # the section order is untouched.
        bugs = text.index("## Bugs")
        questions = text.index("## Open questions and rulings")
        assert bugs < text.index("### B1") < text.index("### B2") < questions
        assert text.index("## Notable events") < text.index("### N1") < bugs
        assert re.search(r"Disposition:\n\n## Open questions", text)


def test_append_counts_struck_headings_when_allocating():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        close_out.append_entry(slice_dir, "Suggestions", "one", "b")
        close_out.append_entry(slice_dir, "Suggestions", "two", "b")
        text = report(slice_dir).replace(
            "### S2 — two", "### ~~S2 — two~~ — absorbed by P11 (97b5313)")
        (slice_dir / "close-out.md").write_text(text)
        assert close_out.append_entry(slice_dir, "Suggestions", "three", "b") == "S3"


def test_append_into_an_unknown_or_missing_section_raises():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        try:
            close_out.append_entry(slice_dir, "Summary", "x", "y")
            raise AssertionError("Summary takes no entries")
        except ReportError:
            pass
        text = report(slice_dir).replace("## Bugs\n", "## Defects\n")
        (slice_dir / "close-out.md").write_text(text)
        try:
            close_out.append_entry(slice_dir, "Bugs", "x", "y")
            raise AssertionError("a missing heading must raise")
        except ReportError as e:
            assert "no `## Bugs` section" in str(e)


def test_append_without_a_report_raises():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        try:
            close_out.append_entry(slice_dir, "Bugs", "x", "y")
            raise AssertionError("no report must raise")
        except ReportError as e:
            assert "close_out.py init" in str(e)


def test_append_rejects_an_unknown_severity():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        try:
            close_out.append_entry(slice_dir, "Bugs", "x", "y", severity="Blocker")
            raise AssertionError("reviewer severities never reach the report")
        except ReportError:
            pass


# -- counts -----------------------------------------------------------------

def test_entry_counts_ignore_struck_entries():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        assert close_out.entry_counts(slice_dir) == dict.fromkeys(close_out.SECTIONS, 0)
        close_out.append_entry(slice_dir, "Bugs", "one", "b")
        close_out.append_entry(slice_dir, "Bugs", "two", "b")
        close_out.append_entry(slice_dir, "Outstanding actions", "do", "b")
        text = report(slice_dir).replace("### B1 — one", "### ~~B1 — one~~ — dup of B2")
        (slice_dir / "close-out.md").write_text(text)
        counts = close_out.entry_counts(slice_dir)
        assert counts["Bugs"] == 1 and counts["Outstanding actions"] == 1
        assert close_out.counts_line(counts) == "A 1 · N 0 · B 1 · Q 0 · S 0"


# -- stamp ------------------------------------------------------------------

def test_stamp_writes_the_run_shape_and_is_idempotent():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        (slice_dir / "state.json").write_text(json.dumps(STATE))
        header = close_out.stamp_header(slice_dir)
        assert header == ("Run: 2026-08-14 19:49 → 23:53 · 11 phases (8 planned, "
                          "P9, P10, P11 appended) · 2 bail-outs · 1 test round · "
                          "doc phase done")
        text = report(slice_dir)
        assert "<not yet stamped>" not in text
        assert text.count("Run:") == 1
        # The block is the header wrapped, then the blank line, then Summary.
        block = text[text.index("Run:"):text.index("## Summary")]
        assert " ".join(block.split()) == header
        assert block.endswith("\n\n")
        # Re-stamping with cost replaces the block rather than adding one.
        state = dict(STATE, cost={"cost_usd": 118.41, "planner_share": 0.18,
                                  "research_share": 0.04, "rework_share": 0.14})
        (slice_dir / "state.json").write_text(json.dumps(state))
        header2 = close_out.stamp_header(slice_dir)
        assert header2.endswith("· $118.41 (planner 18 %, research 4 %, rework 14 %)")
        text2 = report(slice_dir)
        assert text2.count("Run:") == 1
        assert " ".join(text2[text2.index("Run:"):text2.index("## Summary")].split()) \
            == header2
        assert close_out.stamp_header(slice_dir) == header2
        assert report(slice_dir) == text2


def test_stamp_omits_what_the_state_does_not_carry():
    """A state.json from before this report (no `bailouts`, no
    `appended_phases`) stamps what it has, and a bailed run says so."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        state = {"created_at": "2026-08-14T19:49:12+02:00",
                 "updated_at": "2026-08-15T01:02:03+02:00",
                 "run_phase": "bailed", "known_phases": ["1"], "test_rounds": 0}
        (slice_dir / "state.json").write_text(json.dumps(state))
        header = close_out.stamp_header(slice_dir)
        assert header == ("Run: 2026-08-14 19:49 → 2026-08-15 01:02 · 1 phase · "
                          "0 test rounds · run bailed")
        assert "bail-out" not in header and "$" not in header


def test_stamp_counts_operator_questions_among_bail_outs():
    state = dict(STATE, bailouts=[{"reason": "operator_question", "question": True},
                                  {"reason": "gate_red", "question": False}])
    header = close_out.run_header(state)
    assert "2 bail-outs (1 operator question)" in header


def test_stamp_needs_a_state_file_and_a_run_line():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        try:
            close_out.stamp_header(slice_dir)
            raise AssertionError("no state.json must raise")
        except ReportError as e:
            assert "state.json" in str(e)
        (slice_dir / "state.json").write_text(json.dumps(STATE))
        text = report(slice_dir).replace("Run: <not yet stamped>\n", "")
        (slice_dir / "close-out.md").write_text(text)
        try:
            close_out.stamp_header(slice_dir)
            raise AssertionError("no Run: line must raise")
        except ReportError as e:
            assert "`Run:` line" in str(e)


# -- CLI --------------------------------------------------------------------

def run_cli(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = close_out.main(list(argv))
        except SystemExit as e:      # argparse's own usage errors
            code = e.code
    return code, out.getvalue(), err.getvalue()


def test_cli_init_append_counts_stamp():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        code, out, _ = run_cli("init", str(slice_dir))
        assert code == 0 and out.startswith("created ")
        code, out, _ = run_cli("init", str(slice_dir))
        assert code == 0 and out.startswith("exists ")
        code, out, _ = run_cli("append", str(slice_dir), "--section", "Bugs",
                               "--headline", "h", "--body", "b",
                               "--severity", "nit", "--provenance", "P1 r1")
        assert code == 0 and out.strip() == "B1"
        code, out, _ = run_cli("counts", str(slice_dir))
        assert code == 0 and out.strip() == "A 0 · N 0 · B 1 · Q 0 · S 0"
        (slice_dir / "state.json").write_text(json.dumps(STATE))
        code, out, _ = run_cli("stamp", str(slice_dir))
        assert code == 0 and out.startswith("Run: 2026-08-14 19:49")
        code, _, err = run_cli("append", str(slice_dir), "--section", "Bugs",
                               "--headline", "h", "--body", "b",
                               "--severity", "Blocker")
        assert code == 2 and "invalid choice" in err
        code, _, err = run_cli("counts", str(Path(tmp) / "nowhere"))
        assert code == 2 and "not found" in err


if __name__ == "__main__":
    _tests = [v for k, v in sorted(globals().items())
              if k.startswith("test_") and callable(v)]
    for _fn in _tests:
        _fn()
        print(f"ok  {_fn.__name__}")
    print(f"\n{len(_tests)} passed")
