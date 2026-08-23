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


# The two labels every driver-minted entry carries; tests not about the
# labels pass these so the smoke counts stay quiet.
FULL = {"consequence": "none", "provenance": "P1 r1"}


def zero_counts():
    return {**dict.fromkeys(close_out.SECTIONS, 0), close_out.UNSHAPED: 0,
            close_out.NO_CONSEQUENCE: 0, close_out.NO_PROVENANCE: 0}


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
        # Ahead of the first section the file says, as a comment, which
        # tool writes entries and what the three labels are for — and no
        # more: the shape is the tool's, so there is no sample entry to
        # mistake for one and no operator line to grep up.
        head = text[:text.index("## Summary")]
        assert "close_out.py append" in head and "close_out.py note" in head
        assert (head.index("**Consequence:**") < head.index("**Provenance:**")
                < head.index("**Disposition:**"))
        assert "### " not in head
        assert not re.search(r"^\s*\*{0,2}Disposition:", head, re.M)
        # …and none of it counts as an entry, a stray heading, or a
        # label-less entry.
        counts = close_out.entry_counts(slice_dir)
        assert counts == zero_counts()
        assert close_out.counts_line(counts) == "A 0 · N 0 · B 0 · Q 0 · S 0"


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
            consequence="an operator sees a Python traceback  instead of the "
                        "named refusal; the hook still fails closed.",
            provenance="P3 review r1 F3 (advisory)", severity="minor")
        n1 = close_out.append_entry(
            slice_dir, "Notable events", "P3 bailed blocked", "venue off the wire")
        b2 = close_out.append_entry(
            slice_dir, "Bugs", "second bug", "body")
        assert (b1, n1, b2) == ("B1", "N1", "B2")
        text = report(slice_dir)
        # Body, then the Consequence paragraph (whitespace-normalised, like
        # the headline), then the Provenance/Disposition tail — the three
        # labels bold, in the shape's order.
        assert ("### B1 — presync exits with a traceback · minor\n\n"
                "`kubeconfig.identity()` checks that `ca.crt` exists but not that "
                "it parses.\n\nExit is still non-zero.\n\n"
                "**Consequence:** an operator sees a Python traceback instead of "
                "the named refusal; the hook still fails closed.\n\n"
                "**Provenance:** P3 review r1 F3 (advisory)\n**Disposition:**\n"
                ) in text
        # An entry minted without either label still carries the operator's
        # line — and counts as one the smoke check names.
        assert ("### N1 — P3 bailed blocked\n\nvenue off the wire\n\n"
                "**Disposition:**\n") in text
        # Entries land in their own section, before the next heading, and
        # the section order is untouched.
        bugs = text.index("## Bugs")
        questions = text.index("## Open questions and rulings")
        assert bugs < text.index("### B1") < text.index("### B2") < questions
        assert text.index("## Notable events") < text.index("### N1") < bugs
        assert re.search(r"\*\*Disposition:\*\*\n\n## Open questions", text)
        counts = close_out.entry_counts(slice_dir)
        assert counts[close_out.NO_CONSEQUENCE] == 2   # N1 and B2
        assert counts[close_out.NO_PROVENANCE] == 2


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


def test_quoted_headings_inside_fences_are_not_headings():
    """The entry rules ask agents to quote liberally; a quoted `## Bugs` or
    `### B7` inside a fenced block must move no section boundary and shift
    no id."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        close_out.append_entry(
            slice_dir, "Notable events", "the doc-writer quoted a whole page",
            "The page as shipped:\n\n```markdown\n## Bugs\n\n### B7 — not an "
            "entry\n\n## Suggestions\n```\n\nwhich is wrong because …", **FULL)
        assert close_out.append_entry(slice_dir, "Bugs", "real bug", "b", **FULL) == "B1"
        assert close_out.append_entry(
            slice_dir, "Notable events", "two", "b", **FULL) == "N2"
        counts = close_out.entry_counts(slice_dir)
        assert counts == {**zero_counts(), "Notable events": 2, "Bugs": 1}
        text = report(slice_dir)
        # B1 landed under the real Bugs heading (the last one — the first
        # is the quoted one), after the quoted block.
        assert text.index("```\n\nwhich is wrong") < text.rindex("\n## Bugs\n") \
            < text.index("### B1 — real bug")


def test_headings_inside_html_comments_are_not_headings():
    """The template's section charters are comments, and an entry may
    quote headings inside one: nothing inside `<!-- … -->` is a section
    boundary, an entry, or a stray heading —
    whether the comment is one line or many. A `<!--` mid-line in prose
    opens nothing."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        close_out.append_entry(
            slice_dir, "Bugs", "a comment quoting headings",
            "Seen in the page source:\n\n<!-- one-liner: ### B9 — not real -->\n"
            "<!--\n## Suggestions\n### B7 — inside a block comment\n"
            "### N4 — wrong letter, still hidden\n-->\n"
            "and the prose mentions `<!--` here without opening anything.\n"
            "### B8 — a real heading after the comment, hand-written")
        assert close_out.append_entry(slice_dir, "Bugs", "next", "b") == "B9"
        counts = close_out.entry_counts(slice_dir)
        assert counts["Bugs"] == 3 and counts["Suggestions"] == 0
        assert counts[close_out.UNSHAPED] == 0
        # The one section a comment could hide a boundary from: `## Bugs`
        # itself stays where it is, and B9 landed under it.
        text = report(slice_dir)
        assert text.rindex("\n## Bugs\n") < text.index("### B1") < text.index("### B9 — next")


def test_counts_report_headings_not_in_entry_shape():
    """An author that wrote `### minor — …` or `### Consult 1 (…) …` instead
    of the id shape has produced no entry the counter can see; the line
    says so rather than reading zero in silence. Ids under the wrong
    section's letter are unshaped too."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        close_out.append_entry(slice_dir, "Bugs", "shaped", "b", **FULL)
        text = report(slice_dir)
        text = text.replace(
            "## Notable events\n",
            "## Notable events\n\n### Consult 1 (2026-08-15) appended P4\n\nbody\n\n"
            "### Test phase round 1 — clean\n\nbody\n\n### S1 — a suggestion's id\n\nbody\n")
        text = text.replace(
            "## Bugs\n",
            "## Bugs\n\n### minor — the reset is unbounded\n\nbody\n\nDisposition:\n")
        (slice_dir / "close-out.md").write_text(text)
        counts = close_out.entry_counts(slice_dir)
        assert counts["Bugs"] == 1 and counts["Notable events"] == 0
        assert counts[close_out.UNSHAPED] == 4
        assert close_out.counts_line(counts) == \
            "A 0 · N 0 · B 1 · Q 0 · S 0 · 4 headings not in entry shape"
        # A struck entry is in shape, and one stray heading reads singular.
        text = report(slice_dir).replace("### B1 — shaped", "### ~~B1 — shaped~~ — dup")
        text = text.replace("### Test phase round 1 — clean\n\nbody\n\n", "")
        text = text.replace("### S1 — a suggestion's id\n\nbody\n", "")
        text = text.replace("### minor — the reset is unbounded\n\nbody\n\nDisposition:\n", "")
        (slice_dir / "close-out.md").write_text(text)
        assert close_out.counts_line(close_out.entry_counts(slice_dir)) == \
            "A 0 · N 0 · B 0 · Q 0 · S 0 · 1 heading not in entry shape"


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
        assert close_out.entry_counts(slice_dir) == zero_counts()
        close_out.append_entry(slice_dir, "Bugs", "one", "b", **FULL)
        close_out.append_entry(slice_dir, "Bugs", "two", "b", **FULL)
        close_out.append_entry(slice_dir, "Outstanding actions", "do", "b", **FULL)
        text = report(slice_dir).replace("### B1 — one", "### ~~B1 — one~~ — dup of B2")
        (slice_dir / "close-out.md").write_text(text)
        counts = close_out.entry_counts(slice_dir)
        assert counts["Bugs"] == 1 and counts["Outstanding actions"] == 1
        assert close_out.counts_line(counts) == "A 1 · N 0 · B 1 · Q 0 · S 0"


def test_counts_name_live_entries_missing_a_consequence_or_provenance_line():
    """The line the operator triages on is the one authors dropped most
    (156, 157: none labelled); the count names it. Bare labels count as
    present (the check is content, not typography), a label inside a fence
    is quoted text, and a struck entry — nobody's to decide on — is not
    checked."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        close_out.append_entry(slice_dir, "Bugs", "both bold", "b", **FULL)
        close_out.append_entry(slice_dir, "Bugs", "bare labels", "b")
        close_out.append_entry(slice_dir, "Bugs", "no consequence", "b",
                               provenance="P2 r1")
        close_out.append_entry(slice_dir, "Bugs", "labels only in a fence",
                               "```\n**Consequence:** quoted\nProvenance: q\n```")
        close_out.append_entry(slice_dir, "Suggestions", "struck, unlabelled", "b")
        text = report(slice_dir)
        text = text.replace(
            "### B2 — bare labels\n\nb\n\n**Disposition:**",
            "### B2 — bare labels\n\nb\n\nConsequence: none.\n\n"
            "Provenance: P1 r1\nDisposition:")
        text = text.replace("### S1 — struck, unlabelled",
                            "### ~~S1 — struck, unlabelled~~ — dup of B1")
        (slice_dir / "close-out.md").write_text(text)
        counts = close_out.entry_counts(slice_dir)
        assert counts["Bugs"] == 4 and counts["Suggestions"] == 0
        assert counts[close_out.NO_CONSEQUENCE] == 2     # B3, B4
        assert counts[close_out.NO_PROVENANCE] == 1      # B4
        assert close_out.counts_line(counts) == (
            "A 0 · N 0 · B 4 · Q 0 · S 0 · 2 entries without a Consequence "
            "line · 1 entry without a Provenance line")
        # …and both trailers ride behind the unshaped one when all apply.
        line = close_out.counts_line({**counts, close_out.UNSHAPED: 1})
        assert line.endswith("· 1 heading not in entry shape · 2 entries "
                             "without a Consequence line · 1 entry without "
                             "a Provenance line")


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
        # The block is the header wrapped, then the blank line, then the
        # head comment (untouched by the stamp).
        block = text[text.index("Run:"):text.index("<!-- Entries are written")]
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
        block2 = text2[text2.index("Run:"):text2.index("<!-- Entries are written")]
        assert " ".join(block2.split()) == header2
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
    # Zero is a fact the state carries and is said; only an absent key is
    # omitted (the previous test).
    assert "· 0 bail-outs ·" in close_out.run_header(dict(STATE, bailouts=[]))


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


# -- note -------------------------------------------------------------------

def test_note_lands_above_the_consequence_line_dated_and_signed():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        close_out.append_entry(slice_dir, "Bugs", "one", "body one", **FULL,
                               severity="minor")
        close_out.append_entry(slice_dir, "Bugs", "two", "body two", **FULL)
        para = close_out.add_note(slice_dir, "B1", " consult  1 ",
                                  "  the premise moved: P4 rewrote it.\n",
                                  date="2026-08-17")
        assert para == "consult 1, 2026-08-17 — the premise moved: P4 rewrote it."
        text = report(slice_dir)
        assert ("### B1 — one · minor\n\nbody one\n\n"
                "consult 1, 2026-08-17 — the premise moved: P4 rewrote it.\n\n"
                "**Consequence:** none\n\n**Provenance:** P1 r1\n**Disposition:**\n\n"
                "### B2 — two\n\nbody two\n\n**Consequence:** none\n\n") in text
        # A second note goes under the first, still above the label; a
        # multi-line note keeps its lines.
        close_out.add_note(slice_dir, "B1", "test-agent", "re-run:\n  still fails",
                           date="2026-08-18")
        text = report(slice_dir)
        assert ("consult 1, 2026-08-17 — the premise moved: P4 rewrote it.\n\n"
                "test-agent, 2026-08-18 — re-run:\n  still fails\n\n"
                "**Consequence:** none\n") in text
        # Nothing else moved, and the counts see the same two entries.
        assert "### B2 — two\n\nbody two\n\n**Consequence:** none" in text
        counts = close_out.entry_counts(slice_dir)
        assert counts == {**zero_counts(), "Bugs": 2}


def test_note_falls_back_to_provenance_then_disposition_then_the_end():
    """An entry from before the Consequence label (0.5.0/0.5.1 shape, bare
    labels) takes the note above `Provenance:`; one with only a
    `Disposition:` line above that; one with no label at all at its
    end — never inside the next entry."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        text = report(slice_dir).replace(
            "\n## Bugs\n",
            "\n### N1 — old shape\n\nold body\n\n"
            "Provenance: P1 r1\nDisposition:\n\n"
            "### N2 — only a disposition\n\nbody two\n\n**Disposition:**\n\n"
            "### N3 — bare\n\nbody three\n\n## Bugs\n")
        (slice_dir / "close-out.md").write_text(text)
        for eid in ("N1", "N2", "N3"):
            close_out.add_note(slice_dir, eid, "consult 1", f"about {eid}",
                               date="2026-08-17")
        text = report(slice_dir)
        assert ("old body\n\nconsult 1, 2026-08-17 — about N1\n\n"
                "Provenance: P1 r1\nDisposition:\n\n### N2") in text
        assert ("body two\n\nconsult 1, 2026-08-17 — about N2\n\n"
                "**Disposition:**\n\n### N3") in text
        assert "body three\n\nconsult 1, 2026-08-17 — about N3\n\n## Bugs" in text
        # A label quoted inside a fence is text, not the anchor.
        close_out.append_entry(slice_dir, "Bugs", "quotes a label",
                               "```\n**Consequence:** quoted\n```\nprose",
                               consequence="real", provenance="read P2")
        close_out.add_note(slice_dir, "B1", "x", "n", date="2026-08-17")
        assert ("```\n**Consequence:** quoted\n```\nprose\n\nx, 2026-08-17 — n\n\n"
                "**Consequence:** real\n") in report(slice_dir)


def test_note_on_an_unknown_id_or_without_text_raises():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        close_out.append_entry(slice_dir, "Bugs", "one", "b", **FULL)
        for eid in ("B2", "X1", "b1", "S1"):
            try:
                close_out.add_note(slice_dir, eid, "who", "text", date="2026-08-17")
                raise AssertionError(f"{eid} must raise")
            except ReportError:
                pass
        for bad in ("", "   \n"):
            try:
                close_out.add_note(slice_dir, "B1", "who", bad, date="2026-08-17")
                raise AssertionError("an empty note must raise")
            except ReportError:
                pass
        try:
            close_out.add_note(slice_dir, "B1", "who", "t", date="17-08-2026")
            raise AssertionError("a malformed date must raise")
        except ReportError:
            pass
        assert "who, " not in report(slice_dir)


def test_note_dates_today_by_default():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        close_out.append_entry(slice_dir, "Bugs", "one", "b", **FULL)
        para = close_out.add_note(slice_dir, "B1", "op", "t")
        assert re.fullmatch(r"op, \d{4}-\d{2}-\d{2} — t", para)


# -- strike -----------------------------------------------------------------

def test_strike_rewrites_the_heading_and_leaves_the_body():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        close_out.append_entry(slice_dir, "Bugs", "one", "body one", **FULL,
                               severity="nit")
        close_out.append_entry(slice_dir, "Bugs", "two", "body two", **FULL)
        head = close_out.strike_entry(slice_dir, "B1",
                                      "  absorbed by  P4 (19640d9) ", by=" consult  1 ")
        assert head == "### ~~B1 — one · nit~~ — absorbed by P4 (19640d9); struck by consult 1"
        text = report(slice_dir)
        assert (head + "\n\nbody one\n\n**Consequence:** none\n\n"
                "**Provenance:** P1 r1\n**Disposition:**\n\n### B2 — two\n") in text
        # Without --by, no signature; the reason is whitespace-normalised.
        assert close_out.strike_entry(slice_dir, "B2", "duplicate\nof B1") == \
            "### ~~B2 — two~~ — duplicate of B1"
        # counts sees both as struck; ids are still not reused.
        counts = close_out.entry_counts(slice_dir)
        assert counts == zero_counts()
        assert close_out.append_entry(slice_dir, "Bugs", "three", "b", **FULL) == "B3"


def test_strike_refuses_an_already_struck_or_unknown_entry():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        close_out.append_entry(slice_dir, "Bugs", "one", "b", **FULL)
        close_out.strike_entry(slice_dir, "B1", "dup")
        before = report(slice_dir)
        for eid, why in (("B1", "already struck"), ("B7", "unknown"), ("Q1", "unknown")):
            try:
                close_out.strike_entry(slice_dir, eid, "again")
                raise AssertionError(f"{eid} ({why}) must raise")
            except ReportError as e:
                assert ("already struck" in str(e)) == (why == "already struck")
        assert report(slice_dir) == before


# -- list -------------------------------------------------------------------

def test_list_shows_ids_headlines_and_consequence_lines_only():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        close_out.append_entry(
            slice_dir, "Bugs", "presync traceback", "long body\n\nmore body",
            consequence="an operator sees a traceback\ninstead of the named refusal.",
            provenance="read P3 r1", severity="minor")
        close_out.append_entry(slice_dir, "Bugs", "no consequence", "b",
                               provenance="read P1")
        close_out.append_entry(slice_dir, "Bugs", "gone", "b", **FULL, severity="nit")
        close_out.append_entry(slice_dir, "Suggestions", "an idea", "b",
                               consequence="none", provenance="witnessed P2")
        close_out.strike_entry(slice_dir, "B3", "duplicate of B1", by="consult 1")
        # A hand-typed heading not in the shape is shown, marked.
        text = report(slice_dir).replace(
            "## Notable events\n", "## Notable events\n\n### Consult 1 appended P4\n\nbody\n")
        (slice_dir / "close-out.md").write_text(text)
        assert close_out.list_view(slice_dir) == (
            "## Outstanding actions\n(none)\n"
            "## Notable events\n(not in entry shape) Consult 1 appended P4\n"
            "## Bugs\n"
            "B1 — presync traceback · minor\n"
            "    Consequence: an operator sees a traceback instead of the named refusal.\n"
            "B2 — no consequence\n    (no Consequence line)\n"
            "~~B3~~ — gone · nit — duplicate of B1; struck by consult 1\n"
            "## Open questions and rulings\n(none)\n"
            "## Suggestions\nS1 — an idea\n    Consequence: none")
        # Bodies never leak — not the entry's, not a bare Consequence
        # paragraph's continuation past a blank line.
        assert "long body" not in close_out.list_view(slice_dir)


# -- render -----------------------------------------------------------------

def _bugs(text):
    return text[text.index("\n## Bugs\n"):text.index("\n## Open questions")]


def test_render_orders_live_by_severity_then_unshaped_then_struck_folded():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        for headline, sev in (("a nit", "nit"), ("ungraded", None), ("a major", "major"),
                              ("a minor", "minor"), ("struck major", "major"),
                              ("cosmetic", "cosmetic"), ("struck nit", "nit")):
            close_out.append_entry(slice_dir, "Bugs", headline, f"body of {headline}",
                                   consequence=f"c of {headline}",
                                   provenance="read P1", severity=sev)
        close_out.strike_entry(slice_dir, "B7", "dup of B1", by="consult 1")
        close_out.strike_entry(slice_dir, "B5", "resolved by P4 (19640d9): re-run")
        # A hand-typed heading in the middle of the section.
        text = report(slice_dir).replace(
            "### B4 — a minor",
            "### Test phase round 1 — clean\n\nhand-typed\n\n### B4 — a minor")
        (slice_dir / "close-out.md").write_text(text)
        before = report(slice_dir)
        line = close_out.render_report(slice_dir)
        assert "Bugs: 5 live, 2 struck, 1 not in entry shape" in line
        assert line.startswith("Outstanding actions: 0 live, 0 struck; ")
        after = report(slice_dir)
        bugs = _bugs(after)
        order = [m.group(0) for m in re.finditer(r"^### .*$", bugs, re.M)]
        assert order == [
            "### B3 — a major · major",
            "### B4 — a minor · minor",
            "### B1 — a nit · nit",
            "### B6 — cosmetic · cosmetic",
            "### B2 — ungraded",
            "### Test phase round 1 — clean",
            "### ~~B5 — struck major · major~~ — resolved by P4 (19640d9): re-run",
            "### ~~B7 — struck nit · nit~~ — dup of B1; struck by consult 1",
        ]
        # The struck body is kept, folded once, labels included; the live
        # entries and the hand-typed block are byte-identical to before.
        assert ("### ~~B5 — struck major · major~~ — resolved by P4 (19640d9): re-run\n\n"
                "<details><summary>struck — body kept for the record</summary>\n\n"
                "body of struck major\n\n**Consequence:** c of struck major\n\n"
                "**Provenance:** read P1\n**Disposition:**\n\n</details>\n\n"
                "### ~~B7") in bugs
        for piece in ("### B3 — a major · major\n\nbody of a major\n\n**Consequence:** c of "
                      "a major\n\n**Provenance:** read P1\n**Disposition:**\n\n",
                      "### Test phase round 1 — clean\n\nhand-typed\n\n"):
            assert piece in before and piece in after
        # The section preamble — Focus line and charter — the head comment,
        # the title and the Run line are untouched.
        assert after[:after.index("\n## Bugs\n")] == before[:before.index("\n## Bugs\n")]
        assert bugs.startswith("\n## Bugs\n\nFocus: <!-- doc-writer: the worst one first")
        assert "<!-- Defects the run will not fix." in bugs
        assert after[after.index("\n## Open questions"):] == \
            before[before.index("\n## Open questions"):]
        # counts are the same before and after.
        assert close_out.entry_counts(slice_dir) == {**zero_counts(), "Bugs": 5,
                                                    close_out.UNSHAPED: 1}
        # A second render is a byte-identical no-op.
        assert close_out.render_report(slice_dir) == line
        assert report(slice_dir) == after


def test_render_orders_other_sections_by_id_and_keeps_empty_ones():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        for i in range(3):
            close_out.append_entry(slice_dir, "Suggestions", f"s{i + 1}", "b", **FULL)
        close_out.append_entry(slice_dir, "Notable events", "n1", "b", **FULL)
        # Struck first in arrival order, and the section's last entry — the
        # file's last block, ending in a single newline — moves up.
        close_out.strike_entry(slice_dir, "S1", "dup of S3")
        text = report(slice_dir)
        s2, s3 = text.index("### S2"), text.index("### S3")
        block2, block3 = text[s2:s3], text[s3:]
        assert block3.endswith("**Disposition:**\n") and not block3.endswith("\n\n")
        text = text[:s2] + block3 + "\n" + block2.rstrip("\n") + "\n"
        (slice_dir / "close-out.md").write_text(text)
        before = report(slice_dir)
        line = close_out.render_report(slice_dir)
        assert "Suggestions: 2 live, 1 struck" in line
        assert "Notable events: 1 live, 0 struck" in line
        after = report(slice_dir)
        tail = after[after.index("\n## Suggestions\n"):]
        order = re.findall(r"^### .*$", tail, re.M)
        assert order == ["### S2 — s2", "### S3 — s3", "### ~~S1 — s1~~ — dup of S3"]
        assert tail.endswith("**Disposition:**\n\n</details>\n")
        # Untouched sections are byte-identical, empty ones included.
        assert after[:after.index("\n## Suggestions\n")] == \
            before[:before.index("\n## Suggestions\n")]
        assert "## Open questions and rulings\n\nFocus:" in after
        assert close_out.render_report(slice_dir) == line
        assert report(slice_dir) == after
        assert close_out.entry_counts(slice_dir) == {**zero_counts(), "Suggestions": 2,
                                                    "Notable events": 1}


def test_render_reads_headings_outside_fences_and_comments_only():
    """A `###` quoted in a fence or in a comment is text — it starts no
    block, so a fenced heading travels with its entry and a fenced `##`
    moves no section."""
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        close_out.append_entry(
            slice_dir, "Bugs", "quotes a report", "seen:\n\n```markdown\n## Bugs\n\n"
            "### B9 — quoted\n```\n\n<!-- ### B8 — in a comment -->\nafter", **FULL,
            severity="nit")
        close_out.append_entry(slice_dir, "Bugs", "major", "b", **FULL, severity="major")
        before = report(slice_dir)
        close_out.render_report(slice_dir)
        after = report(slice_dir)
        bugs = _bugs(after)
        # B2 (major) now leads; B1's quoted headings moved with it, intact.
        assert bugs.index("### B2 — major") < bugs.index("### B1 — quotes a report")
        assert ("### B1 — quotes a report · nit\n\nseen:\n\n```markdown\n## Bugs\n\n"
                "### B9 — quoted\n```\n\n<!-- ### B8 — in a comment -->\nafter\n\n"
                "**Consequence:**") in bugs
        assert after[:after.index("\n## Bugs\n")] == before[:before.index("\n## Bugs\n")]
        assert close_out.render_report(slice_dir)
        assert report(slice_dir) == after


def test_note_lands_inside_the_fold_of_a_rendered_struck_entry():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        close_out.init_report(slice_dir)
        close_out.append_entry(slice_dir, "Bugs", "one", "body", **FULL)
        close_out.append_entry(slice_dir, "Bugs", "bare struck", "just a body")
        close_out.strike_entry(slice_dir, "B1", "dup")
        close_out.strike_entry(slice_dir, "B2", "dup too")
        # B2 hand-stripped of every label: the note has only the fold's
        # end to go before.
        text = report(slice_dir).replace("just a body\n\n**Disposition:**\n", "just a body\n")
        (slice_dir / "close-out.md").write_text(text)
        close_out.render_report(slice_dir)
        close_out.add_note(slice_dir, "B1", "op", "still true", date="2026-08-17")
        close_out.add_note(slice_dir, "B2", "op", "no labels here", date="2026-08-17")
        text = report(slice_dir)
        assert ("<details><summary>struck — body kept for the record</summary>\n\n"
                "body\n\nop, 2026-08-17 — still true\n\n**Consequence:** none\n\n"
                "**Provenance:** P1 r1\n**Disposition:**\n\n</details>\n\n### ~~B2") in text
        assert ("just a body\n\nop, 2026-08-17 — no labels here\n\n</details>\n") in text
        # …and the render after that is still a no-op.
        before = report(slice_dir)
        close_out.render_report(slice_dir)
        assert report(slice_dir) == before


def test_render_without_a_report_raises():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        try:
            close_out.render_report(slice_dir)
            raise AssertionError("no report must raise")
        except ReportError:
            pass


# -- the dispatch line ------------------------------------------------------

def test_dispatch_line_names_the_report_and_this_tool_once():
    line = close_out.dispatch_line("/specs/slices/007_x/close-out.md")
    assert line.startswith("The slice's close-out report is /specs/slices/007_x/close-out.md.")
    tool = str(Path(close_out.__file__).resolve())
    assert tool.endswith("/close_out.py")
    assert line.count(tool) == 1
    # The invocation is shown whole — verb, then the report's own path — so
    # the first call an agent makes is the right one (W2: every session used
    # to guess `list --file …` or `list <report>`, fail, and read --help).
    assert f"`python3 {tool} append|note|strike /specs/slices/007_x/close-out.md …`" in line
    assert "`list`" in line and "never edit the file by hand" in line
    assert not line.endswith("\n")


def test_slice_dir_of_accepts_the_directory_or_the_report():
    assert close_out.slice_dir_of("/s/007_x") == Path("/s/007_x")
    assert close_out.slice_dir_of("/s/007_x/close-out.md") == Path("/s/007_x")
    # Any .md resolves to its directory — present or not, so `list <report>`
    # works before `init` has created the file.
    assert close_out.slice_dir_of(Path("/nowhere/008_y/close-out.md")) == Path("/nowhere/008_y")


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
        # The report's path works wherever the directory does (W2) — here
        # before the file exists, which is when an agent's first `list` lands.
        code, _, err = run_cli("list", str(slice_dir / "close-out.md"))
        assert code == 2 and "does not exist" in err and "init" in err
        code, out, _ = run_cli("init", str(slice_dir / "close-out.md"))
        assert code == 0 and out.startswith("created ")
        code, out, _ = run_cli("init", str(slice_dir))
        assert code == 0 and out.startswith("exists ")
        code, out, _ = run_cli("append", str(slice_dir), "--section", "Bugs",
                               "--headline", "h", "--body", "b",
                               "--consequence", "none", "--severity", "nit",
                               "--provenance", "P1 r1")
        assert code == 0 and out.strip() == "B1"
        code, out, _ = run_cli("counts", str(slice_dir))
        assert code == 0 and out.strip() == "A 0 · N 0 · B 1 · Q 0 · S 0"
        # The consequence is not optional at the CLI: the driver always has
        # one, and an entry without it is what the smoke count exists for.
        code, _, err = run_cli("append", str(slice_dir), "--section", "Bugs",
                               "--headline", "h", "--body", "b")
        assert code == 2 and "--consequence" in err and "required" in err
        (slice_dir / "state.json").write_text(json.dumps(STATE))
        code, out, _ = run_cli("stamp", str(slice_dir))
        assert code == 0 and out.startswith("Run: 2026-08-14 19:49")
        code, _, err = run_cli("append", str(slice_dir), "--section", "Bugs",
                               "--headline", "h", "--body", "b",
                               "--consequence", "none", "--severity", "Blocker")
        assert code == 2 and "invalid choice" in err
        code, _, err = run_cli("counts", str(Path(tmp) / "nowhere"))
        assert code == 2 and "not found" in err


def test_cli_note_strike_list_render():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = make_slice(tmp)
        run_cli("init", str(slice_dir))
        for h, sev in (("first", "nit"), ("second", "major")):
            run_cli("append", str(slice_dir), "--section", "Bugs", "--headline", h,
                    "--body", "b", "--consequence", f"c {h}", "--provenance", "read P1",
                    "--severity", sev)
        code, out, _ = run_cli("note", str(slice_dir), "B1", "--by", "consult 1",
                               "--text", "premise moved", "--date", "2026-08-17")
        assert code == 0 and out.strip() == "B1 noted"
        assert ("consult 1, 2026-08-17 — premise moved\n\n**Consequence:** c first"
                in report(slice_dir))
        code, out, _ = run_cli("strike", str(slice_dir), "B1", "--reason",
                               "duplicate of B2", "--by", "consult 1")
        assert code == 0
        assert out.strip() == "### ~~B1 — first · nit~~ — duplicate of B2; struck by consult 1"
        code, _, err = run_cli("strike", str(slice_dir), "B1", "--reason", "again")
        assert code == 2 and "already struck" in err
        code, _, err = run_cli("strike", str(slice_dir), "B9", "--reason", "x")
        assert code == 2 and "no entry B9" in err
        code, _, err = run_cli("note", str(slice_dir), "B9", "--by", "x", "--text", "t")
        assert code == 2 and "no entry B9" in err
        code, out, _ = run_cli("list", str(slice_dir))
        assert code == 0
        assert ("## Bugs\n~~B1~~ — first · nit — duplicate of B2; struck by consult 1\n"
                "B2 — second · major\n    Consequence: c second\n") in out
        code, out, _ = run_cli("render", str(slice_dir))
        assert code == 0 and "Bugs: 1 live, 1 struck" in out
        text = report(slice_dir)
        bugs = _bugs(text)
        assert bugs.index("### B2 — second") < bugs.index("### ~~B1") \
            < bugs.index("<details><summary>struck")
        code, out2, _ = run_cli("render", str(slice_dir))
        assert code == 0 and out2 == out and report(slice_dir) == text
        code, out, _ = run_cli("counts", str(slice_dir))
        assert out.strip() == "A 0 · N 0 · B 1 · Q 0 · S 0"


if __name__ == "__main__":
    _tests = [v for k, v in sorted(globals().items())
              if k.startswith("test_") and callable(v)]
    for _fn in _tests:
        _fn()
        print(f"ok  {_fn.__name__}")
    print(f"\n{len(_tests)} passed")
