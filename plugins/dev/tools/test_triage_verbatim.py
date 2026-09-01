"""Tests for triage_verbatim — the guard on a triage status document's inlined card text.

The fixture is a synthetic pair written out in full below: a dump with two cards
(one carrying a deeper heading and a fenced block that quotes a `## ` line) and a
status document with five items over them — a plain one, a card split in two
(`#712a` / `#712b`), an id backed by no card, and a card the dump does not carry.
Written literally rather than generated, so the demotion the tool applies is checked
against a hand-written expectation rather than against itself.

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
    assert code == 0

    # And restoring a clean document is a no-op, byte for byte.
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
