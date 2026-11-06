"""Tests for slice_cards — /dev:triage's check that every card a slice.md embeds
matches the run's raw dump.

The slice_023 fixtures are PilotAppSpecs slice 023, the slice whose copy lost
most of P-47 and all of P-49: its five cards as a dump writes them now
(`triage_raw.md`), and three slice.md files — the cards section as filed
(`023_as_filed`, fenced), the same lines re-embedded as blockquotes
(`023_quoted_as_filed`) and every card copied whole (`023_whole`). The small
cases build a dump and slice folders in a throwaway directory.

Stdlib only, like the workflow's other suites — `@with_workspace` stands in for
the fixture, so each test still takes `ws` and still collects under pytest.

Run: `python3 ${CLAUDE_PLUGIN_ROOT}/tools/test_slice_cards.py` or via pytest.
"""

import contextlib
import importlib.util
import io
import tempfile
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "slice_cards", Path(__file__).resolve().parent / "slice_cards.py"
)
slice_cards = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(slice_cards)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "slice_023"
DUMP_023 = FIXTURES / "triage_raw.md"
IDS_023 = ["P-36", "P-54", "P-47", "P-53", "P-49"]

DUMP = """\
# Triage 2026-11-06 — raw material

## The cards

### For row 001

### AB-1 — First card

> State: Accepted
>
> **Description:**
>
> ```
> ### B1 — a heading inside a fence
> ```
>
> **Comments:**
>
> none

### AB-2 — Second card

> State: New
>
> One line.
"""

AB_2 = """\
### AB-2 — Second card

> State: New
>
> One line.
"""


def with_workspace(fn):
    """A throwaway directory per test, handed in as `ws`.

    The wrapper takes no arguments, so pytest collects it as a plain test —
    hence no functools.wraps, which would expose the wrapped signature and
    have pytest demand a `ws` fixture this suite does not define.
    """
    def wrapper():
        with tempfile.TemporaryDirectory() as tmp:
            fn(Path(tmp))
    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper


def run_cli(*argv):
    """main() with its streams captured — (exit code, stdout, stderr).

    argparse leaves through SystemExit on a usage error; that is a CLI result
    like any other here, so it comes back as a code too.
    """
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = slice_cards.main([str(arg) for arg in argv])
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue(), err.getvalue()


def write_dump(ws, text=DUMP):
    path = ws / "triage_2026-11-06_raw.md"
    path.write_text(text, encoding="utf-8")
    return path


def make_slice(ws, name, cards):
    """A slice folder whose slice.md opens with prose and then holds `cards`."""
    folder = ws / name
    folder.mkdir()
    (folder / "slice.md").write_text(
        f"# {name}\n\n## Source material\n\n### Cards, verbatim from the tracker\n\n{cards}",
        encoding="utf-8")
    return folder


def check(ws, cards, dump=DUMP):
    """One slice holding `cards`, checked against `dump`."""
    return run_cli(write_dump(ws, dump), make_slice(ws, "001_slice", cards))


def fixture_card(name, card_id):
    text = (FIXTURES / name / "slice.md").read_text(encoding="utf-8")
    return next(card for card in slice_cards.parse_cards(text) if card.id == card_id)


# --- slice 023 -------------------------------------------------------------------

def test_023_whole_is_whole():
    code, out, err = run_cli(DUMP_023, FIXTURES / "023_whole")
    assert code == 0, err
    assert out == "023_whole: 5 cards whole (P-36, P-54, P-47, P-53, P-49)\n"
    assert err == ""


def test_023_quoted_heading_does_not_end_its_card():
    text = (FIXTURES / "023_whole" / "slice.md").read_text(encoding="utf-8")
    cards = slice_cards.parse_cards(text)
    assert [card.id for card in cards] == IDS_023
    p47 = cards[2]
    assert p47.defect is None
    assert any(line.startswith("### B9 — ") for line in p47.body)
    assert len(p47.body) == 27
    assert p47.body[-1].startswith("Plan review of the open cards, 2026-10-24")


def test_023_dump_holds_the_five_cards_whole():
    dump = slice_cards.load_dump(DUMP_023)
    assert list(dump) == IDS_023
    assert all(len(copies) == 1 and copies[0].defect is None for copies in dump.values())


def test_023_quoted_as_filed_loses_p47_and_p49():
    code, out, err = run_cli(DUMP_023, FIXTURES / "023_quoted_as_filed")
    assert code == 2
    assert out == "023_quoted_as_filed: 2 of 5 cards not whole\n"
    lines = err.splitlines()
    assert len(lines) == 2, err
    assert lines[0].startswith("023_quoted_as_filed: P-47: body differs from the dump's at "
                               "its line 6 (the dump's copy has 27 lines, slice.md's 5)")
    assert lines[0].endswith("the dump has (blank), slice.md (missing) (after slice.md line 47)")
    assert lines[1].startswith("023_quoted_as_filed: P-49: body differs from the dump's at "
                               "its line 7 (the dump's copy has 27 lines, slice.md's 7)")
    assert 'the dump has "### B13 — PilotApp frontend' in lines[1]
    assert 'slice.md "Triage research, 2026-10-25' in lines[1]
    assert lines[1].endswith("(slice.md line 80)")


def test_023_p36_p54_p53_were_copied_whole():
    dump = slice_cards.load_dump(DUMP_023)
    for card_id in ("P-36", "P-54", "P-53"):
        card = fixture_card("023_quoted_as_filed", card_id)
        assert slice_cards.card_defect(card, dump) is None, card_id


def test_023_as_filed_has_every_card_outside_a_blockquote():
    code, out, err = run_cli(DUMP_023, FIXTURES / "023_as_filed")
    assert code == 2
    assert out == "023_as_filed: 5 of 5 cards not whole\n"
    lines = err.splitlines()
    assert [line.split(": ")[1] for line in lines] == IDS_023
    for line in lines:
        assert "no blockquote — every line of the card starts with `>`, a blank one too" in line
    assert lines[0].endswith("(slice.md line 7)")


def test_several_slice_dirs_one_bad_reports_every_one():
    code, out, err = run_cli(DUMP_023, FIXTURES / "023_whole",
                             FIXTURES / "023_quoted_as_filed", FIXTURES / "023_whole")
    assert code == 2
    assert out.splitlines() == [
        "023_whole: 5 cards whole (P-36, P-54, P-47, P-53, P-49)",
        "023_quoted_as_filed: 2 of 5 cards not whole",
        "023_whole: 5 cards whole (P-36, P-54, P-47, P-53, P-49)",
    ]
    assert err.count("023_quoted_as_filed: ") == 2


# --- the format ------------------------------------------------------------------

@with_workspace
def test_a_fence_inside_a_quoted_body_is_harmless(ws):
    code, out, err = check(ws, DUMP.split("### For row 001\n\n")[1])
    assert code == 0, err
    assert out == "001_slice: 2 cards whole (AB-1, AB-2)\n"
    card = slice_cards.parse_cards(DUMP)[0]
    assert card.body[4:7] == ("```", "### B1 — a heading inside a fence", "```")


@with_workspace
def test_a_blank_line_splitting_the_blockquote_is_flagged(ws):
    code, out, err = check(ws, AB_2.replace(">\n", "\n"))
    assert code == 2
    assert out == "001_slice: 1 of 1 cards not whole\n"
    # slice.md: heading line 1, … the card's heading on 7, its blank split on 10.
    assert err == ("001_slice: AB-2: a blank line splits the card's blockquote in two — "
                   "a blank line of the card is `>` alone (slice.md line 10)\n")


@with_workspace
def test_an_unquoted_line_after_the_blockquote_is_flagged(ws):
    code, _, err = check(ws, AB_2 + "\nTriage research: a paragraph swallowed.\n")
    assert code == 2
    assert err == ("001_slice: AB-2: this line is outside the card's blockquote — every "
                   "line of the card starts with `>`, a blank one too (slice.md line 13)\n")


@with_workspace
def test_an_unquoted_line_running_on_from_the_blockquote_is_flagged(ws):
    code, _, err = check(ws, AB_2 + "a lazy continuation\n")
    assert code == 2
    assert "outside the card's blockquote" in err
    assert err.endswith("(slice.md line 12)\n")


@with_workspace
def test_a_heading_with_nothing_under_it_has_no_blockquote(ws):
    code, _, err = check(ws, "### AB-2 — Second card\n\n")
    assert code == 2
    assert err == ("001_slice: AB-2: no blockquote — nothing under the heading "
                   "(slice.md line 7)\n")


@with_workspace
def test_a_card_absent_from_the_dump(ws):
    code, out, err = check(ws, AB_2.replace("AB-2", "AB-9"))
    assert code == 2
    assert out == "001_slice: 1 of 1 cards not whole\n"
    assert err == "001_slice: AB-9: not in the dump (slice.md line 7)\n"


@with_workspace
def test_a_title_differing(ws):
    code, _, err = check(ws, AB_2.replace("Second card", "Second card, renamed"))
    assert code == 2
    assert err == ('001_slice: AB-2: title differs from the dump\'s: the dump has '
                   '"Second card", slice.md "Second card, renamed" (slice.md line 7)\n')


@with_workspace
def test_a_body_line_differing_names_its_line(ws):
    code, _, err = check(ws, AB_2.replace("One line.", "One line, edited."))
    assert code == 2
    assert err == ("001_slice: AB-2: body differs from the dump's at its line 3 (the dump's "
                   "copy has 3 lines, slice.md's 3): the dump has \"One line.\", slice.md "
                   "\"One line, edited.\" (slice.md line 11)\n")


@with_workspace
def test_a_long_differing_line_is_shortened(ws):
    long = "x" * 200
    code, _, err = check(ws, AB_2.replace("One line.", long))
    assert code == 2
    assert f'slice.md "{"x" * 79}…"' in err


@with_workspace
def test_quote_spacing_trailing_whitespace_and_end_blanks_compare_equal(ws):
    cards = "### AB-2 — Second card   \n\n>\n>State: New   \n>\n>One line.\t\n>\n"
    code, out, err = check(ws, cards)
    assert code == 0, err
    assert out == "001_slice: 1 card whole (AB-2)\n"


@with_workspace
def test_non_card_headings_are_ignored_and_end_a_card(ws):
    cards = ("### Plan row 012, verbatim\n\nA row.\n\n### For row 012\n\n" + AB_2
             + "\n#### Notes\n\nNot part of the card.\n\n### AB-2 - a hyphen, not a card\n")
    code, out, err = check(ws, cards)
    assert code == 0, err
    assert out == "001_slice: 1 card whole (AB-2)\n"


@with_workspace
def test_a_slice_with_no_card(ws):
    code, out, err = check(ws, "### Plan row 012\n\nNo cards here.\n")
    assert code == 0
    assert out == "001_slice: no card embedded\n"
    assert err == ""


@with_workspace
def test_the_dump_copy_broken_itself(ws):
    dump = DUMP + "\n### AB-3 — Third card\n\nState: New\n"
    code, _, err = check(ws, AB_2.replace("AB-2 — Second card", "AB-3 — Third card"), dump)
    assert code == 2
    assert err.startswith("001_slice: AB-3: the dump's copy is not whole itself: no blockquote")
    assert err.endswith("(dump line 29)\n")


@with_workspace
def test_the_dump_holding_a_card_twice_alike(ws):
    code, out, err = check(ws, AB_2, DUMP + "\n" + AB_2)
    assert code == 0, err
    assert out == "001_slice: 1 card whole (AB-2)\n"


@with_workspace
def test_the_dump_holding_a_card_twice_differently(ws):
    code, _, err = check(ws, AB_2, DUMP + "\n" + AB_2.replace("One line.", "Another line."))
    assert code == 2
    assert err == ("001_slice: AB-2: the dump holds it 2 times, not alike "
                   "(dump lines 21, 27)\n")


# --- the CLI ---------------------------------------------------------------------

@with_workspace
def test_a_slice_dir_without_slice_md_is_reported_and_the_others_still_checked(ws):
    dump = write_dump(ws)
    empty = ws / "002_empty"
    empty.mkdir()
    good = make_slice(ws, "003_good", AB_2)
    code, out, err = run_cli(dump, empty, good)
    assert code == 2
    assert err == f"002_empty: no slice.md in {empty}\n"
    assert out == "003_good: 1 card whole (AB-2)\n"


@with_workspace
def test_a_missing_dump_is_a_usage_error(ws):
    code, out, err = run_cli(ws / "nope.md", make_slice(ws, "001_slice", AB_2))
    assert code == 2
    assert out == ""
    assert err == f"Error: dump not found: {ws / 'nope.md'}\n"


def test_no_slice_dir_is_a_usage_error():
    code, _, _ = run_cli(DUMP_023)
    assert code == 2


if __name__ == "__main__":
    _tests = [v for k, v in sorted(globals().items())
              if k.startswith("test_") and callable(v)]
    for _fn in _tests:
        _fn()
        print(f"ok  {_fn.__name__}")
    print(f"\n{len(_tests)} passed")
