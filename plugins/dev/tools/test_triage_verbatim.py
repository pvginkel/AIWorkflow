"""Tests for triage_verbatim — the guard on a triage status document's inlined card text.

The fixture is a synthetic pair written out in full below: a dump with two cards
(one carrying a deeper heading and a fenced block that quotes a `## ` line) and a
status document with five items over them — a plain one, a card split in two
(`#712a` / `#712b`), an id backed by no card, and a card the dump does not carry.
Written literally rather than generated, so the demotion the tool applies is checked
against a hand-written expectation rather than against itself. A second pair beside
it carries the same shapes with the readable ids a tracker writes (`KC-701`), and
one test splices the two into the mixed document a cutover leaves behind. A third
pair is the one the `Ask:` tests rule on: a single card whose text carries a
`TF_VAR_*`, a quoted phrase, a sentence that wraps, and the same identifier twice —
once escaped, as a card that went through an editor has it.

One test runs the real pair out of the spec repo's history (`git show`, nothing
checked out) and asserts every card-backed item is verbatim; it skips cleanly where
that repo or that commit is not present.

Stdlib only, like the workflow's other suites — each test takes no fixture, so they
collect under pytest as they stand.

Run: `python3 ${CLAUDE_PLUGIN_ROOT}/tools/test_triage_verbatim.py` or via pytest.
"""

import contextlib
import importlib.util
import io
import subprocess
import tempfile
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "triage_verbatim", Path(__file__).resolve().parent / "triage_verbatim.py"
)
triage_verbatim = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(triage_verbatim)
Precondition = triage_verbatim.Precondition


# ---------------------------------------------------------------------------
# The synthetic pair
# ---------------------------------------------------------------------------

RAW = """\
# Triage 2099-01-01 — raw material

Every tagged card, whole and verbatim. This is the archive.

## #701 — First card, whose body has depth and a fence

- URL: https://trello.com/c/aaa/701
- Reporter: Someone (@someone)
- Labels: KubeCoder, Improvement

### Description

The card names `_is_stuck` and KUBECODER_CLIENT_TOKEN_NAME.

#### A deeper heading

```md
## Not a card boundary
```

### Comments

None.

## #712 — Second card, two asks in one

- URL: https://trello.com/c/bbb/712
- Reporter: Someone (@someone)
- Labels: KubeCoder

### Description

Two asks: retire `_is_stuck`, and rename KUBECODER_CLIENT_TOKEN_NAME.

### Comments

None.
"""

# #701's section demoted by two — `### ` → `##### `, `#### ` → `###### `, and the
# `## ` inside the fence left exactly as the card wrote it.
CARD_701 = """\
- URL: https://trello.com/c/aaa/701
- Reporter: Someone (@someone)
- Labels: KubeCoder, Improvement

##### Description

The card names `_is_stuck` and KUBECODER_CLIENT_TOKEN_NAME.

###### A deeper heading

```md
## Not a card boundary
```

##### Comments

None.\
"""

CARD_712 = """\
- URL: https://trello.com/c/bbb/712
- Reporter: Someone (@someone)
- Labels: KubeCoder

##### Description

Two asks: retire `_is_stuck`, and rename KUBECODER_CLIENT_TOKEN_NAME.

##### Comments

None.\
"""

STATUS = f"""\
# Triage 2099-01-01 — adjudication

Each item inlines its own source under **Card text:** so nothing needs looking up.
Headings inside those inlined sources are **demoted by two levels** throughout.

## How to rule

Write on each item's `Ruling:` line, in your own words.

## Major

### #701 — First card — https://trello.com/c/aaa/701

- Source: card #701
- Ask: "The card names `_is_stuck`"
- Category: Major — "names `_is_stuck`"
- Ruling: —

**Card text:**

{CARD_701}

### #712a — Second card, retire the flag — https://trello.com/c/bbb/712

- Source: card #712
- Ask: "retire `_is_stuck`"
- Category: Major — "retire `_is_stuck`"
- Ruling: —

**Card text:**

{CARD_712}

## Minor

### #712b — Second card, rename the token — https://trello.com/c/bbb/712

- Source: card #712
- Ask: "rename KUBECODER_CLIENT_TOKEN_NAME"
- Category: Minor — "rename KUBECODER_CLIENT_TOKEN_NAME"
- Ruling: —

**Card text:**

{CARD_712}

### #S2 — A findings-document section, on no card — n/a

- Source: findings document § S2
- Ask: "the reviewer's S2"
- Category: Minor — "S2"
- Ruling: —

**Card text:**

The findings document's own words, which no dump carries.

### #790 — A card the dump does not carry — https://trello.com/c/ccc/790

- Source: card #790
- Ask: "fetched after the dump was written"
- Category: Minor — "later"
- Ruling: —

**Card text:**

Whatever was pasted in by hand.
"""


# ---------------------------------------------------------------------------
# The same pair again, with the readable ids a tracker writes
# ---------------------------------------------------------------------------

RAW_READABLE = """\
# Triage 2099-02-02 — raw material

Every marked card, whole and verbatim. This is the archive.

## KC-701 — First card

- Reporter: Someone (@someone)

### Description

The card names `_is_stuck`.

## Card KC-712 — Second card, two asks in one

- Reporter: Someone (@someone)

### Description

Two asks: retire `_is_stuck`, and rename KUBECODER_CLIENT_TOKEN_NAME.
"""

KC_701 = """\
- Reporter: Someone (@someone)

##### Description

The card names `_is_stuck`.\
"""

KC_712 = """\
- Reporter: Someone (@someone)

##### Description

Two asks: retire `_is_stuck`, and rename KUBECODER_CLIENT_TOKEN_NAME.\
"""

STATUS_READABLE = f"""\
# Triage 2099-02-02 — adjudication

## Major

### KC-701 — First card

- Source: card KC-701
- Ruling: —

**Card text:**

{KC_701}

### KC-712a — Second card, retire the flag

- Source: card KC-712
- Ruling: —

**Card text:**

{KC_712}

## Minor

### KC-712b — Second card, rename the token

- Source: card KC-712
- Ruling: —

**Card text:**

{KC_712}

### S7 — A findings-document section, on no card

- Source: findings document § S7
- Ruling: —

**Card text:**

The findings document's own words, which no dump carries.

### KC-790 — A card the dump does not carry

- Source: card KC-790
- Ruling: —

**Card text:**

Whatever was pasted in by hand.
"""


# ---------------------------------------------------------------------------
# The pair the Ask tests rule on
# ---------------------------------------------------------------------------

RAW_ASK = """\
# Triage 2099-03-03 — raw material

## KC-57 — The deploy leaks TF_VAR_* into the pod's environment

- URL: https://issues.example.org/issue/KC-57
- Reporter: Someone (@someone)

### Description

Every TF_VAR_* the workspace sets reaches the container, so `_is_stuck` and
KUBECODER_CLIENT_TOKEN_STAGING are readable by anything the pod runs.

The operator calls it "a sharp edge", and wants the list filtered to what the
deploy actually needs.

### Comments

A comment wrote it as `\\_is_stuck`, escape and all.
"""

CARD_ASK = """\
- URL: https://issues.example.org/issue/KC-57
- Reporter: Someone (@someone)

##### Description

Every TF_VAR_* the workspace sets reaches the container, so `_is_stuck` and
KUBECODER_CLIENT_TOKEN_STAGING are readable by anything the pod runs.

The operator calls it "a sharp edge", and wants the list filtered to what the
deploy actually needs.

##### Comments

A comment wrote it as `\\_is_stuck`, escape and all.\
"""

# The quote every Ask test swaps out, and the line it sits on — the messages carry
# that number, so it is asserted rather than searched for.
DEFAULT_ASK = '- Ask: "Every TF_VAR_* the workspace sets reaches the container"'
ASK_LINE = 8

STATUS_ASK = f"""\
# Triage 2099-03-03 — adjudication

## Major

### KC-57 — The deploy leaks the workspace's variables

- Source: card KC-57
{DEFAULT_ASK}
- Category: Major — "readable by anything the pod runs"
- Ruling: —

**Card text:**

{CARD_ASK}
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def with_workspace(fn):
    """A throwaway directory per test, handed in as `ws`."""
    def wrapper():
        with tempfile.TemporaryDirectory() as tmp:
            fn(Path(tmp))
    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper


@contextlib.contextmanager
def raises(exc):
    try:
        yield
    except exc:
        return
    raise AssertionError(f"expected {exc.__name__}")


def write_pair(ws, status=STATUS, raw=RAW):
    status_path, raw_path = ws / "triage.md", ws / "triage_raw.md"
    status_path.write_text(status)
    raw_path.write_text(raw)
    return status_path, raw_path


def ask_pair(ws, ask=DEFAULT_ASK):
    """The Ask pair, with KC-57's quote replaced by `ask` — one line or several."""
    return write_pair(ws, status=STATUS_ASK.replace(DEFAULT_ASK, ask, 1), raw=RAW_ASK)


def ask_of(status_path):
    """The one `- Ask:` line the document now carries — a restore leaves exactly
    one, whether the quote wrapped before it or not."""
    lines = [line for line in status_path.read_text().split("\n")
             if line.lstrip().startswith("- Ask:")]
    assert len(lines) == 1, lines
    return lines[0]


def verdicts(results):
    return {r.item_id: r.verdict for r in results}


def run_main(*argv):
    """main() with its output captured — returns (exit code, printed lines)."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
        code = triage_verbatim.main([str(a) for a in argv])
    return code, buf.getvalue().splitlines()


# ---------------------------------------------------------------------------
# check
# ---------------------------------------------------------------------------

@with_workspace
def test_a_faithful_pair_is_ok_throughout(ws):
    results, code = triage_verbatim.check(*write_pair(ws))
    assert code == 1, "the pair carries #790, which the dump does not"
    assert verdicts(results) == {
        "701": "ok", "712a": "ok", "712b": "ok",
        "S2": "no card", "790": "missing in raw",
    }, verdicts(results)


@with_workspace
def test_a_split_item_reads_its_whole_card(ws):
    """#712a and #712b share #712's one section — both are checked against all of it."""
    status = STATUS.replace(f"{CARD_712}\n\n## Minor", f"{CARD_712[:-6]}\n\n## Minor", 1)
    results, _ = triage_verbatim.check(*write_pair(ws, status=status))
    assert verdicts(results)["712a"] == "diff", verdicts(results)
    assert verdicts(results)["712b"] == "ok", "the second half was left intact"


@with_workspace
def test_the_first_differing_line_is_the_one_reported(ws):
    """The editor's emphasis damage, mid-paragraph, in the second of two items."""
    good = "Two asks: retire `_is_stuck`, and rename KUBECODER_CLIENT_TOKEN_NAME."
    bad = "Two asks: retire `\\_is_stuck`, and rename KUBECODER*CLIENT_TOKEN*NAME."
    status = STATUS.replace(good, bad)          # both the Ask line and both blocks
    status = status.replace(f'- Ask: "{bad}"', f'- Ask: "{good}"')
    results, code = triage_verbatim.check(*write_pair(ws, status=status))
    assert code == 1
    first = next(r for r in results if r.item_id == "712a")
    assert first.verdict == "diff"
    assert first.status_text == bad, first.status_text
    assert first.raw_text == good, first.raw_text
    # The line number points into the status document, at the corrupted line.
    lines = (ws / "triage.md").read_text().split("\n")
    assert lines[first.line - 1] == bad, lines[first.line - 1]


@with_workspace
def test_a_differing_heading_is_reported_in_its_demoted_form(ws):
    """The raw side of a DIFF is shown as the status document should carry it."""
    status = STATUS.replace("##### Description\n\nThe card names",
                            "#### Description\n\nThe card names", 1)
    results, _ = triage_verbatim.check(*write_pair(ws, status=status))
    first = next(r for r in results if r.item_id == "701")
    assert first.status_text == "#### Description", first.status_text
    assert first.raw_text == "##### Description", first.raw_text


@with_workspace
def test_padding_blank_lines_are_not_significant(ws):
    status = STATUS.replace("**Card text:**\n\n- URL: https://trello.com/c/aaa/701",
                            "**Card text:**\n\n\n\n- URL: https://trello.com/c/aaa/701", 1)
    results, _ = triage_verbatim.check(*write_pair(ws, status=status))
    assert verdicts(results)["701"] == "ok"


@with_workspace
def test_trailing_whitespace_is_a_difference(ws):
    """Verbatim means verbatim — nothing but the padding is normalised."""
    status = STATUS.replace("The card names `_is_stuck` and KUBECODER_CLIENT_TOKEN_NAME.\n\n"
                            "###### A deeper heading",
                            "The card names `_is_stuck` and KUBECODER_CLIENT_TOKEN_NAME. \n\n"
                            "###### A deeper heading", 1)
    results, _ = triage_verbatim.check(*write_pair(ws, status=status))
    assert verdicts(results)["701"] == "diff"


# ---------------------------------------------------------------------------
# Format errors
# ---------------------------------------------------------------------------

@with_workspace
def test_an_item_without_a_card_text_block_is_a_format_error(ws):
    status = STATUS.replace("**Card text:**\n\n" + CARD_701, "(the source, see the dump)", 1)
    status_path, raw_path = write_pair(ws, status=status)
    with raises(Precondition):
        triage_verbatim.check(status_path, raw_path)
    assert run_main("check", status_path, raw_path)[0] == 2


@with_workspace
def test_a_document_with_no_items_is_a_format_error(ws):
    """Arguments the wrong way round is the case this catches — silently reporting
    nothing would be the worst answer available."""
    status_path, raw_path = write_pair(ws)
    assert run_main("check", raw_path, status_path)[0] == 2


@with_workspace
def test_an_unreadable_file_is_a_format_error(ws):
    status_path, raw_path = write_pair(ws)
    assert run_main("check", status_path, ws / "absent.md")[0] == 2
    assert run_main("restore", ws / "absent.md", raw_path)[0] == 2


# ---------------------------------------------------------------------------
# restore
# ---------------------------------------------------------------------------

@with_workspace
def test_restore_rewrites_the_block_and_nothing_else(ws):
    """The operator's ruling stays; the corrupted quote goes back to the dump's."""
    ruled = STATUS.replace('- Ask: "retire `_is_stuck`"\n- Category: Major — '
                           '"retire `_is_stuck`"\n- Ruling: —',
                           '- Ask: "retire `_is_stuck`"\n- Category: Major — '
                           '"retire `_is_stuck`"\n- Ruling: **agreed** — "712: yes, both."', 1)
    corrupt = ruled.replace(
        "##### Description\n\nTwo asks: retire `_is_stuck`, and rename "
        "KUBECODER_CLIENT_TOKEN_NAME.",
        "##### Description\n\nTwo asks: retire `\\_is_stuck`, and rename "
        "KUBECODER*CLIENT_TOKEN*NAME.", 1)
    assert corrupt != ruled
    status_path, raw_path = write_pair(ws, status=corrupt)

    results = triage_verbatim.restore(status_path, raw_path)
    assert verdicts(results)["712a"] == "diff"
    assert verdicts(results)["701"] == "ok"
    assert status_path.read_text() == ruled, "restore moved something outside the block"


@with_workspace
def test_restore_reports_and_is_idempotent(ws):
    corrupt = STATUS.replace("###### A deeper heading", "###### A deeper headings", 1)
    status_path, raw_path = write_pair(ws, status=corrupt)

    code, printed = run_main("restore", status_path, raw_path)
    assert code == 0
    assert printed == ["#701  restored", "#712a  ok", "#712b  ok",
                       "#S2  no card", "#790  missing in raw"], printed
    assert status_path.read_text() == STATUS

    # Second pass: nothing left to do, and the bytes do not move.
    code, printed = run_main("restore", status_path, raw_path)
    assert code == 0
    assert printed[0] == "#701  ok", printed
    assert status_path.read_text() == STATUS
    # And a check now agrees, bar the item whose card the dump never had.
    assert run_main("check", status_path, raw_path)[1][0] == "#701  ok"


@with_workspace
def test_restore_fills_a_block_that_was_emptied(ws):
    """Nothing left to keep the padding from, so the shape's own padding is used."""
    emptied = STATUS.replace(f"**Card text:**\n\n{CARD_701}\n", "**Card text:**\n", 1)
    status_path, raw_path = write_pair(ws, status=emptied)
    results = triage_verbatim.restore(status_path, raw_path)
    assert verdicts(results)["701"] == "diff"
    assert status_path.read_text() == STATUS
    assert triage_verbatim.check(status_path, raw_path)[0][0].verdict == "ok"


@with_workspace
def test_restore_leaves_an_item_whose_card_is_missing_alone(ws):
    status_path, raw_path = write_pair(ws)
    triage_verbatim.restore(status_path, raw_path)
    assert status_path.read_text() == STATUS


# ---------------------------------------------------------------------------
# Exit codes
# ---------------------------------------------------------------------------

@with_workspace
def test_check_exits_zero_only_when_every_card_backed_item_is_ok(ws):
    # The same document without the item whose card the dump never carried.
    clean = STATUS[:STATUS.index("### #790 — ")].rstrip("\n") + "\n"
    status_path, raw_path = write_pair(ws, status=clean)
    code, printed = run_main("check", status_path, raw_path)
    assert code == 0, printed
    assert printed == ["#701  ok", "#712a  ok", "#712b  ok", "#S2  no card"], printed


# ---------------------------------------------------------------------------
# Readable ids — the same properties, the other id shape
# ---------------------------------------------------------------------------

def test_dump_headings_take_either_id_shape():
    """`## #701`, `## Card #701`, `## KC-701`, `## Card KC-701`, and a stray `#`
    before a readable id. A `## ` heading naming no card still ends a section."""
    cards = triage_verbatim.parse_raw(
        ("## #701 — a\nbody 701\n\n## Card #702 — b\nbody 702\n\n"
         "## KC-703 — c\nbody 703\n\n## Card KC-704 — d\nbody 704\n\n"
         "## #KC-705 — e\nbody 705\n\n## Not a card\nbody none\n").split("\n"))
    assert sorted(cards) == ["701", "702", "KC-703", "KC-704", "KC-705"], \
        sorted(cards)
    assert cards["701"].body == ["body 701", ""]
    assert cards["KC-705"].body == ["body 705", ""]
    # The heading line rides along for the ask, which may quote the title.
    assert cards["701"].heading == "## #701 — a"


def test_item_ids_take_either_shape_with_the_split_suffix():
    """A suffixed item belongs to the card its id names, in both shapes; an id
    that is no card id at all is backed by no section."""
    doc = ["# Triage — adjudication", "", "## Major", ""]
    for item_id in ("#472", "472b", "KC-472", "KC-472b", "#KC-472c", "#S2"):
        doc += [f"### {item_id} — item {item_id} — n/a", "",
                "**Card text:**", "", "body", ""]
    items = triage_verbatim.parse_status(doc)
    assert [(i.item_id, i.card) for i in items] == [
        ("472", "472"), ("472b", "472"), ("KC-472", "KC-472"),
        ("KC-472b", "KC-472"), ("KC-472c", "KC-472"), ("S2", None)]


@with_workspace
def test_a_readable_pair_is_read_throughout(ws):
    results, code = triage_verbatim.check(
        *write_pair(ws, status=STATUS_READABLE, raw=RAW_READABLE))
    assert code == 1, "the pair carries KC-790, which the dump does not"
    assert verdicts(results) == {
        "KC-701": "ok", "KC-712a": "ok", "KC-712b": "ok",
        "S7": "no card", "KC-790": "missing in raw",
    }, verdicts(results)


@with_workspace
def test_a_readable_split_item_reads_its_whole_card(ws):
    """KC-712a and KC-712b share KC-712's one section — both see all of it."""
    status = STATUS_READABLE.replace(f"{KC_712}\n\n## Minor",
                                     f"{KC_712[:-6]}\n\n## Minor", 1)
    results, _ = triage_verbatim.check(
        *write_pair(ws, status=status, raw=RAW_READABLE))
    assert verdicts(results)["KC-712a"] == "diff", verdicts(results)
    assert verdicts(results)["KC-712b"] == "ok", "the second half was left intact"


@with_workspace
def test_every_line_cites_an_id_the_way_it_was_written(ws):
    """A readable id stands alone; anything else keeps its `#`."""
    corrupt = STATUS_READABLE.replace("The card names `_is_stuck`.",
                                      "The card names `\\_is_stuck`.", 1)
    code, printed = run_main("check", *write_pair(ws, status=corrupt,
                                                  raw=RAW_READABLE))
    assert code == 1
    assert printed[0].startswith("KC-701  DIFF  line "), printed
    assert "`\\_is_stuck`" in printed[0] and "≠" in printed[0], printed[0]
    assert printed[1:] == ["KC-712a  ok", "KC-712b  ok", "#S7  no card",
                           "KC-790  missing in raw"], printed


@with_workspace
def test_one_document_may_carry_both_id_shapes(ws):
    """A triage pass that straddles a tracker cutover: the cards filed before it
    keep their numbers, the ones after have readable ids, and both check."""
    raw = RAW + "\n" + RAW_READABLE[RAW_READABLE.index("## KC-701"):]
    status = (STATUS[:STATUS.index("### #790 — ")]
              + STATUS_READABLE[STATUS_READABLE.index("### KC-701"):
                                STATUS_READABLE.index("### KC-790")])
    results, code = triage_verbatim.check(*write_pair(ws, status=status, raw=raw))
    assert code == 0, [triage_verbatim.format_result(r) for r in results]
    assert [(r.item_id, r.verdict) for r in results] == [
        ("701", "ok"), ("712a", "ok"), ("712b", "ok"), ("S2", "no card"),
        ("KC-701", "ok"), ("KC-712a", "ok"), ("KC-712b", "ok"),
        ("S7", "no card")]


# ---------------------------------------------------------------------------
# The ask — the session's own quote of the card, checked the same way
# ---------------------------------------------------------------------------

def test_an_ask_is_read_to_where_the_block_moves_on():
    """The value runs to the next bullet, a blank line or the card-text marker; the
    continuation lines join on with single spaces, and the line's indentation is
    kept for the rewrite."""
    doc = ["### KC-9 — an item", "", '  - Ask: "the first line',
           '    and the second"', "  - Category: Major", "", "**Card text:**"]
    ask = triage_verbatim.parse_ask(doc, 1, 6)
    assert (ask.line, ask.end, ask.indent) == (2, 4, "  ")
    assert ask.value == '"the first line and the second"'
    assert triage_verbatim.parse_ask(doc[:2] + doc[4:], 1, 4) is None


@with_workspace
def test_a_clean_ask_is_ok_and_adds_no_line(ws):
    """A quote the card carries prints exactly what the card-text check printed."""
    assert run_main("check", *ask_pair(ws)) == (0, ["KC-57  ok"])
    curly = '- Ask: “Every TF_VAR_* the workspace sets reaches the container”'
    assert run_main("check", *ask_pair(ws, curly)) == (0, ["KC-57  ok"])


@with_workspace
def test_an_escaped_underscore_in_the_ask_is_caught_and_restored(ws):
    """The quote wraps over the card's own line break, so the two are compared with
    their whitespace collapsed and the restored quote is one line of it."""
    damaged = ('- Ask: "so `\\_is_stuck` and KUBECODER_CLIENT_TOKEN_STAGING '
               'are readable"')
    status_path, raw_path = ask_pair(ws, damaged)
    assert run_main("check", status_path, raw_path)[0] == 1

    assert run_main("restore", status_path, raw_path) == (
        0, ["KC-57  ok", "KC-57  ask restored"])
    assert ask_of(status_path) == ('- Ask: "so `_is_stuck` and '
                                   'KUBECODER_CLIENT_TOKEN_STAGING are readable"')
    assert run_main("check", status_path, raw_path)[0] == 0


@with_workspace
def test_the_eaten_token_in_the_ask_is_caught_and_restored(ws):
    """`KUBECODER_CLIENT_TOKEN_<NAME>`, the pair of underscores read as emphasis."""
    damaged = ('- Ask: "KUBECODER*CLIENT_TOKEN*STAGING are readable by anything '
               'the pod runs"')
    status_path, raw_path = ask_pair(ws, damaged)
    assert run_main("check", status_path, raw_path)[0] == 1
    run_main("restore", status_path, raw_path)
    assert ask_of(status_path) == ('- Ask: "KUBECODER_CLIENT_TOKEN_STAGING are '
                                   'readable by anything the pod runs"')


@with_workspace
def test_the_tf_var_case_is_caught_restored_and_settles(ws):
    """2026-09-19: the card said `TF_VAR_*`, the quote came back `TF*VAR*\\*`, and
    this tool said ok — the run this check exists for, start to finish."""
    damaged = '- Ask: "Every TF*VAR*\\* the workspace sets reaches the container"'
    status_path, raw_path = ask_pair(ws, damaged)

    code, printed = run_main("check", status_path, raw_path)
    assert code == 1
    assert printed == [
        "KC-57  ok",
        f"KC-57  ASK  line {ASK_LINE}: Every TF*VAR*\\* the workspace sets reaches "
        "the container  ≠  not in the card's text"], printed

    assert run_main("restore", status_path, raw_path) == (
        0, ["KC-57  ok", "KC-57  ask restored"])
    # Byte for byte the document the session should have written.
    assert status_path.read_text() == STATUS_ASK
    assert run_main("check", status_path, raw_path) == (0, ["KC-57  ok"])

    # And a second restore rewrites nothing at all.
    before = status_path.read_bytes()
    assert run_main("restore", status_path, raw_path) == (0, ["KC-57  ok"])
    assert status_path.read_bytes() == before


@with_workspace
def test_an_elided_ask_is_checked_fragment_by_fragment(ws):
    """One half of the quote is the card's, the other is not: only that half is
    reported, and the elision survives the restore."""
    damaged = ('- Ask: "Every TF_VAR_* the workspace sets … so `\\_is_stuck` and '
               'KUBECODER_CLIENT_TOKEN_STAGING are readable"')
    status_path, raw_path = ask_pair(ws, damaged)

    code, printed = run_main("check", status_path, raw_path)
    assert code == 1
    assert len(printed) == 2 and printed[1].startswith(
        f"KC-57  ASK  line {ASK_LINE}: so `\\_is_stuck`"), printed

    run_main("restore", status_path, raw_path)
    assert ask_of(status_path) == (
        '- Ask: "Every TF_VAR_* the workspace sets … so `_is_stuck` and '
        'KUBECODER_CLIENT_TOKEN_STAGING are readable"')


@with_workspace
def test_two_quoted_pieces_joined_by_the_session_are_read_apart(ws):
    """`"a" and "b"` — read as one quote it is in no card, read as two it is."""
    joined = ('- Ask: "Every TF_VAR_* the workspace sets reaches the container" '
              'and the card wants "the list filtered to what the deploy actually '
              'needs"')
    assert run_main("check", *ask_pair(ws, joined)) == (0, ["KC-57  ok"])


@with_workspace
def test_an_ask_may_quote_the_card_s_title(ws):
    """The title is part of the ask, so the heading line is searched as well."""
    title = '- Ask: "The deploy leaks TF_VAR_* into the pod\'s environment"'
    assert run_main("check", *ask_pair(ws, title)) == (0, ["KC-57  ok"])

    damaged = '- Ask: "The deploy leaks TF*VAR*\\* into the pod\'s environment"'
    status_path, raw_path = ask_pair(ws, damaged)
    assert run_main("check", status_path, raw_path)[0] == 1
    run_main("restore", status_path, raw_path)
    assert ask_of(status_path) == title


@with_workspace
def test_an_ask_that_quotes_text_carrying_quotes_is_read_whole(ws):
    """Only the outer pair comes off, or the card's own `"a sharp edge"` would
    split a quote that is perfectly verbatim into pieces."""
    inner = ('- Ask: "The operator calls it "a sharp edge", and wants the list '
             'filtered"')
    assert run_main("check", *ask_pair(ws, inner)) == (0, ["KC-57  ok"])


@with_workspace
def test_a_wrapped_ask_is_read_over_its_lines_and_rewritten_as_one(ws):
    """The continuation lines join with single spaces; the repair puts the value
    back on the one `- Ask:` line the format asks for."""
    wrapped = ('- Ask: "so `\\_is_stuck` and KUBECODER_CLIENT_TOKEN_STAGING are '
               'readable by\n  anything the pod runs"')
    status_path, raw_path = ask_pair(ws, wrapped)

    code, printed = run_main("check", status_path, raw_path)
    assert code == 1
    assert printed[1].startswith(f"KC-57  ASK  line {ASK_LINE}: "), printed

    run_main("restore", status_path, raw_path)
    one_line = ('- Ask: "so `_is_stuck` and KUBECODER_CLIENT_TOKEN_STAGING are '
                'readable by anything the pod runs"')
    assert status_path.read_text() == STATUS_ASK.replace(DEFAULT_ASK, one_line, 1)
    assert run_main("check", status_path, raw_path)[0] == 0


@with_workspace
def test_a_fragment_the_card_has_nowhere_is_left_for_the_session(ws):
    """Nothing to restore from, so the line stays as the session wrote it and the
    exit code says so."""
    invented = '- Ask: "the deploy writes the token to the log"'
    status_path, raw_path = ask_pair(ws, invented)
    before = status_path.read_bytes()

    assert run_main("restore", status_path, raw_path) == (
        1, ["KC-57  ok",
            f"KC-57  ASK unrestorable  line {ASK_LINE}: "
            "the deploy writes the token to the log"])
    assert status_path.read_bytes() == before


@with_workspace
def test_an_ambiguous_fragment_is_left_for_the_session(ws):
    """The card writes `_is_stuck` twice, once escaped: `*is*stuck` matches both
    canonically, and which was quoted is not this tool's to decide."""
    damaged = '- Ask: "`*is*stuck`"'
    status_path, raw_path = ask_pair(ws, damaged)
    before = status_path.read_bytes()

    code, printed = run_main("restore", status_path, raw_path)
    assert code == 1
    assert printed[1] == (f"KC-57  ASK unrestorable  line {ASK_LINE}: "
                          "`*is*stuck`"), printed
    assert status_path.read_bytes() == before


@with_workspace
def test_an_ask_restores_what_it_can_and_reports_the_rest(ws):
    """One fragment the dump settles, one it cannot: the first goes back, the
    second is named, and the run still exits 1."""
    mixed = ('- Ask: "Every TF*VAR*\\* the workspace sets reaches the container … '
             'the deploy writes the token to the log"')
    status_path, raw_path = ask_pair(ws, mixed)

    code, printed = run_main("restore", status_path, raw_path)
    assert code == 1
    assert printed == ["KC-57  ok", "KC-57  ask restored",
                       f"KC-57  ASK unrestorable  line {ASK_LINE}: "
                       "the deploy writes the token to the log"], printed
    assert ask_of(status_path) == (
        '- Ask: "Every TF_VAR_* the workspace sets reaches the container … '
        'the deploy writes the token to the log"')


@with_workspace
def test_an_item_without_an_ask_line_is_not_checked(ws):
    """The shape allows an item with no quote — that is not a format error."""
    status = STATUS_ASK.replace(DEFAULT_ASK + "\n", "", 1)
    status_path, raw_path = write_pair(ws, status=status, raw=RAW_ASK)
    assert triage_verbatim.parse_status(status.split("\n"))[0].ask is None
    assert run_main("check", status_path, raw_path) == (0, ["KC-57  ok"])


@with_workspace
def test_an_ask_on_an_item_with_no_card_to_read_is_not_checked(ws):
    """`no card` and `missing in raw` stand on their own: there is nothing to check
    a quote against, and the corrupted ones below change no line of the output."""
    status = STATUS.replace('- Ask: "the reviewer\'s S2"',
                            '- Ask: "the reviewer\'s \\_S2"', 1)
    status = status.replace('- Ask: "fetched after the dump was written"',
                            '- Ask: "fetched *after* the dump was written"', 1)
    code, printed = run_main("check", *write_pair(ws, status=status))
    assert code == 1, "#790's card is still missing from the dump"
    assert printed == ["#701  ok", "#712a  ok", "#712b  ok",
                       "#S2  no card", "#790  missing in raw"], printed


# ---------------------------------------------------------------------------
# The real pair
# ---------------------------------------------------------------------------

SPEC_REPO = Path("/work/KubeCoderSpecs")
FIXTURE_COMMIT = "ea8cd085"
FIXTURE_STATUS = "handovers/triage_2026-09-01.md"
FIXTURE_RAW = "handovers/triage_2026-09-01_raw.md"


def _git_show(rev_path):
    result = subprocess.run(["git", "-C", str(SPEC_REPO), "show", rev_path],
                            capture_output=True, text=True)
    return result.stdout if result.returncode == 0 else None


@with_workspace
def test_the_real_triage_pair_is_verbatim_throughout(ws):
    """The pair /dev:triage actually wrote on 2026-09-01, eight cards, read out of
    the spec repo's history — the parser's ground truth."""
    if not (SPEC_REPO / ".git").exists():
        print("   (skipped — no spec repo at /work/KubeCoderSpecs)")
        return
    status = _git_show(f"{FIXTURE_COMMIT}:{FIXTURE_STATUS}")
    raw = _git_show(f"{FIXTURE_COMMIT}:{FIXTURE_RAW}")
    if status is None or raw is None:
        print(f"   (skipped — {FIXTURE_COMMIT} not in this clone)")
        return

    status_path, raw_path = write_pair(ws, status=status, raw=raw)
    results, code = triage_verbatim.check(status_path, raw_path)
    assert [r.item_id for r in results] == ["778", "769", "703", "768", "773",
                                            "774", "770", "779"], results
    assert all(r.verdict == "ok" for r in results), \
        [triage_verbatim.format_result(r) for r in results if r.verdict != "ok"]

    # Two of the eight asks were not the card's words even then, which is what the
    # ask check is for: #774 dropped the card's markdown link around its URL, #770
    # trimmed inside a parenthesis without marking the elision. Neither can be put
    # back from the dump — the session has to say what it meant to quote.
    assert {r.item_id: len(r.ask_missing) for r in results if r.ask_missing} == \
        {"774": 1, "770": 1}, [r.ask_missing for r in results if r.ask_missing]
    assert code == 1

    # And restoring leaves the document byte for byte as it was: every card text is
    # already verbatim, and neither ask can be placed.
    triage_verbatim.restore(status_path, raw_path)
    assert status_path.read_text() == status


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"ok   {name}")
            except AssertionError as e:
                failures += 1
                print(f"FAIL {name}: {e}")
    raise SystemExit(1 if failures else 0)
