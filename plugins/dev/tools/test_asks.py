"""Tests for asks — the store of a stage's asks, its render and its read-back.

The renderer is pinned against the `document-format` skill's own example and
quoting rules, read from the plugin's skill, so a skill edit the tool no
longer agrees with fails here; the read-back against the answer lines
PilotApp's writer writes, captured from its `pilot_dsl` package. Stdlib only;
runs standalone and under pytest.

Run: `python3 ${CLAUDE_PLUGIN_ROOT}/tools/test_asks.py` or via pytest.
"""

import contextlib
import importlib.util
import io
import json
import re
import sys
import tempfile
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "asks", Path(__file__).resolve().parent / "asks.py"
)
asks = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(asks)
AskError = asks.AskError

SKILL = (Path(__file__).resolve().parent.parent / "skills" / "document-format"
         / "SKILL.md").read_text(encoding="utf-8")

# (value, the lines PilotApp's pilot_dsl writer writes for `note: <value>`),
# captured from its `_render` (PilotApp backend/packages/pilot-dsl).
PILOT_WRITES = [
    ("Agreed: but only for now", ["note: 'Agreed: but only for now'"]),
    ("'quoted' start", ["note: '''quoted'' start'"]),
    ("#3 first", ["note: '#3 first'"]),
    ("- dash start", ["note: '- dash start'"]),
    ("ends with colon:", ["note: 'ends with colon:'"]),
    ("it's: both' kinds\"", ["note: 'it''s: both'' kinds\"'"]),
    ("line with \u2028 sep", ['note: "line with \\L sep"']),
    ("nel \x85 here", ['note: "nel \\N here"']),
    ("two\nlines \u2028 sep", ['note: "two\\nlines \\L sep"']),
    ("tab\there", ['note: "tab\\there"']),
    ("multi\nline note\n\nwith a gap",
     ["note: |-", "    multi", "    line note", "", "    with a gap"]),
    ("first\n  indented\nlast", ["note: |-", "    first", "      indented", "    last"]),
    ("a fence\n```\nclosed", ["note: |-", "    a fence", "    ```", "    closed"]),
    ("url http://x.y/z#f", ["note: url http://x.y/z#f"]),
    ("unicode é ✓", ["note: unicode é ✓"]),
    ("a\\b", ["note: a\\b"]),
]


def run_cli(*argv, stdin=None):
    out, err = io.StringIO(), io.StringIO()
    old_stdin = sys.stdin
    if stdin is not None:
        sys.stdin = io.StringIO(stdin)
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = asks.main([str(a) for a in argv])
            except SystemExit as e:      # argparse's own usage errors
                code = e.code
    finally:
        sys.stdin = old_stdin
    return code, out.getvalue(), err.getvalue()


def skill_example() -> str:
    return re.search(r"^## An example\n.*?^````markdown\n(.*?)^````$", SKILL,
                     re.S | re.M).group(1)


def example_store() -> dict:
    """The skill's example document, as a store."""
    store = asks.new_store(
        "Moving the newsletter to the new mail provider",
        summary="How the newsletter moves to the new mail provider before the old "
                "contract ends",
        step="t4",
        context=["The old provider's contract ends on the 30th. The new provider already "
                 "sends the password-reset\nmails, so the newsletter is the last sender "
                 "left on the old one."])
    asks.append(
        store, "decision", "Which domain the newsletter sends from",
        "The existing domain, `mail.example.org`, is recommended: nothing new to verify, "
        "and the newsletter\nmoves this week. Once this is answered, the move goes ahead "
        "on the chosen domain.\n\n**What tells them apart.** A domain of its own keeps a "
        "bad campaign from hurting the reset mails'\ndelivery, at the cost of a second "
        "verification, about two days. The list is small and the\ndeadline near, so the "
        "shared domain is the one recommended; it has not been tried at the list's\nfull "
        "size.",
        options=[("Existing domain", "nothing to verify, shares the reset mails' reputation"),
                 ("Own domain", "a second verification, delivery kept apart")],
        recommend="Existing domain")
    asks.append(
        store, "action", "Confirm the sender address in the provider's console",
        "In the provider's console, under Senders, confirm `news@mail.example.org` from the "
        "mail it sends\nyou, then report whether the confirmation went through.",
        options=["Works", "Doesn't"])
    return store


def every_kind() -> dict:
    """A store with an ask of every kind and shape a stage writes."""
    store = asks.new_store("The requirements of slice 031", summary="What slice 031 builds",
                           step="t2", context=["The slice adds the phone's layout."])
    asks.append(store, "decision", "Which layout the phone gets", "Two are possible.",
                options=[("Stacked", "one column"), "Tabs"], recommend="Stacked",
                check="slice 031 completed")
    asks.append(store, "decision", "Card the stale citation", "It is out of scope.",
                proposal="card it in KC\nwith the quoted line")
    asks.append(store, "question", "Which week the release goes out", "No date is set.",
                default="The first Monday of the month")
    asks.append(store, "question", "Who owns the copy", "Nobody is named.")
    asks.append(store, "action", "Restart the store environment", "It holds a stale clone.",
                options=["Works", "Doesn't"], check="env pilot-store running", due="test")
    asks.append(store, "action", "Rotate the token", "It expires tomorrow.")
    return store


def with_answer(text: str, bid: str, lines: list[str]) -> str:
    """`text` with answer lines written into block `bid` as the record writes
    them: after the last line of its mapping, at its first key's indentation
    — in a rendered block, the column of the fence, before its close."""
    out = text.split("\n")
    start = out.index(next(line for line in out if re.fullmatch(rf"```\w+ id={bid}", line)))
    close = out.index("```", start + 1)
    return "\n".join(out[:close] + lines + out[close:])


def scratch_slice(tmp) -> Path:
    slice_dir = Path(tmp) / "slices" / "031_phone_layout"
    slice_dir.mkdir(parents=True)
    return slice_dir


# ---------------------------------------------------------------- pinned to the skill

def test_the_skills_example_renders_from_a_store_byte_for_byte():
    assert asks.render(example_store()) == skill_example()


def test_the_skills_answered_example_reads_back():
    answered = next(block for block in re.findall(r"^````markdown\n(.*?)^````$", SKILL,
                                                  re.S | re.M) if "id=Q1" in block)
    read = asks.read_back(answered)
    assert read["Q1"]["kind"] == "question"
    assert read["Q1"]["lines"] == {
        "answer": "deferred", "by": "agent", "at": "2026-10-12T09:40:00Z",
        "note": "The send day is settled with the schedule task, once the first issue "
                "has gone out.",
        "to": "t6"}


def test_every_value_the_skill_says_to_quote_is_quoted_and_reads_back():
    rule = re.search(r"Quote a value YAML would read as something else: (.*?)\.\s",
                     re.sub(r"\s+", " ", SKILL)).group(1)
    holding, opening = rule.split("or opening with")
    tokens = re.findall(r"`([^`]+)`", holding), re.findall(r"`([^`]+)`", opening)
    assert tokens[0] and tokens[1], rule
    values = [f"a{t}b" for t in tokens[0]] + [f"{t}x" for t in tokens[1]]
    if "a quote" in opening:
        values += ["'x", '"x']
    if "a backtick" in opening:
        values.append("`x")
    for value in values:
        assert asks.scalar(value).startswith('"'), value
        store = asks.new_store("Quoting")
        asks.append(store, "question", "Q", "Body.", default=value)
        asks.append(store, "decision", "D", "Body.", options=[(value, value)],
                    recommend=value)
        store["summary"] = "Quoting"
        text = with_answer(asks.render(store), "Q1", asks.key_value("note", value))
        assert asks.read_back(text)["Q1"]["lines"] == {"note": value}, value
        assert f"recommend: {asks.scalar(value)}" in text


def test_a_line_break_yaml_reads_is_written_as_the_skills_escape():
    sentence = re.search(r"write it as its escape, (.*?), in a double-quoted value", SKILL,
                         re.S).group(1)
    escapes = re.findall(r"`(\\[^`]+)`", sentence)
    chars = {"\\r": "\r", "\\x85": "\x85", "\\u2028": "\u2028", "\\u2029": "\u2029"}
    assert sorted(escapes) == sorted(chars), escapes
    for escape, char in chars.items():
        assert asks.scalar(f"a{char}b") == f'"a{escape}b"'


# ---------------------------------------------------------------- the round trip

def test_a_store_of_every_kind_round_trips_through_pilots_answer_lines():
    store = every_kind()
    text = asks.render(store)
    read = asks.read_back(text)
    assert [(bid, b["kind"], b["lines"]) for bid, b in read.items()] == [
        (e["id"], e["kind"], {}) for e in store["entries"]]
    answers = {
        "D1": ["answer: Tabs", "by: ada", "at: 2026-10-12T09:40:00Z",
               "note: 'Tabs: the phone is wide enough'", "via: chat"],
        "D2": ["answer: Agree", "by: agent", "at: 2026-10-12T09:41:00Z",
               "note: |-", "    It is out of scope:", "    a card holds it."],
        "Q1": ["answer: deferred", "by: agent", "at: 2026-10-12T09:42:00Z",
               "note: The release is the schedule task's.", "to: t6"],
        "Q2": [],
        "A1": ["done: 2026-10-12T10:00:00Z", "by: ada", 'note: "restarted\\nit runs"'],
        "A2": ["answer: Pilot does it", "by: agent", "at: 2026-10-12T09:43:00Z"],
    }
    for bid, lines in answers.items():
        text = with_answer(text, bid, lines)
    states = asks.absorb(store, text)
    got = {e["id"]: e.get("answer_lines") for e in store["entries"]}
    assert got == {
        "D1": {"answer": "Tabs", "by": "ada", "at": "2026-10-12T09:40:00Z",
               "note": "Tabs: the phone is wide enough", "via": "chat"},
        "D2": {"answer": "Agree", "by": "agent", "at": "2026-10-12T09:41:00Z",
               "note": "It is out of scope:\na card holds it."},
        "Q1": {"answer": "deferred", "by": "agent", "at": "2026-10-12T09:42:00Z",
               "note": "The release is the schedule task's.", "to": "t6"},
        "Q2": None,
        "A1": {"done": "2026-10-12T10:00:00Z", "by": "ada", "note": "restarted\nit runs"},
        "A2": {"answer": "Pilot does it", "by": "agent", "at": "2026-10-12T09:43:00Z"},
    }
    assert states == ["D1  answered by ada: Tabs", "D2  answered by agent: Agree",
                      "Q1  deferred to t6 by agent", "Q2  open", "A1  done by ada",
                      "A2  claimed by Pilot, not done"]
    assert asks.render(store) == asks.render(every_kind())   # answers never render


def test_every_value_pilots_writer_writes_reads_back_as_written():
    store = asks.new_store("Notes")
    asks.append(store, "question", "Q", "Body.", default="x")
    text = asks.render(store)
    for value, lines in PILOT_WRITES:
        read = asks.read_back(with_answer(text, "Q1", ["answer: x", "by: ada", *lines]))
        assert read["Q1"]["lines"]["note"] == value.strip(), (value, read)


def test_what_the_renderer_writes_reads_back_as_written():
    values = [v for v, _ in PILOT_WRITES] + [
        "x\x7fy", "bom\ufeffhere", "\\", '"', "'", "---", "...", "? q", ": c", "a:b",
        "trailing space \nnext", "- a\n- b", "#hash\nfirst", "café\tand\nmore"]
    store = asks.new_store("Values")
    asks.append(store, "question", "Q", "Body.", default="x")
    text = asks.render(store)
    for value in values:
        read = asks.read_back(with_answer(text, "Q1", asks.key_value("note", value)))
        assert read["Q1"]["lines"]["note"] == value.strip(), (value, read)


def test_absorb_reads_an_undo_as_an_open_ask_again():
    store = every_kind()
    text = asks.render(store)
    asks.absorb(store, with_answer(text, "Q2", ["answer: Ada", "by: bob"]))
    assert store["entries"][3]["answer_lines"] == {"answer": "Ada", "by": "bob"}
    assert asks.absorb(store, text)[3] == "Q2  open"
    assert "answer_lines" not in store["entries"][3]


def test_absorb_refuses_a_document_that_is_not_the_stores():
    store = every_kind()
    text = asks.render(store)
    other = asks.new_store("Other")
    asks.append(other, "question", "Q", "Body.")
    for doc, says in [
        (asks.render(other), "ask D1 has no block in the document"),
        (text.replace("id=A2", "id=A9"), "block A9 is no ask of the store"),
        (text.replace("```question id=Q2", "```action id=Q2"),
         "ask Q2 is a question in the store and an action in the document"),
    ]:
        try:
            asks.absorb(store, doc)
        except AskError as e:
            assert says in str(e), (says, str(e))
        else:
            raise AssertionError(says)


def test_the_read_back_refuses_what_it_would_misread():
    store = asks.new_store("Refusals")
    asks.append(store, "question", "Q", "Body.", default="x")
    text = asks.render(store)
    for lines, says in [
        (["note: >", "    folded"], "a folded value"),
        (["note: [a, b]"], "a list or a mapping"),
        (["note:", "  - a"], "a list where one value is wanted"),
        (["note:", "  key: a"], "a mapping where one value is wanted"),
        (["answer: a: b"], "holds `: `"),
        (["answer: deferred"], "`answer: deferred` goes with a `to`"),
        (["answer: x", "to: t6"], "`answer: deferred` goes with a `to`"),
        (["answer: x", "via: phone"], "`via: phone` is not one of"),
        (["answer: x", "at: yesterday"], "`at: yesterday` is no date and time"),
        (['note: "open'], "the double-quoted value is not closed"),
        (["note: 'open"], "the single-quoted value is not closed"),
        (['note: "bad \\q"'], "`\\q` is no escape"),
        (["note: x", "note: y"], "`note` is written twice"),
        (["answer:x"], "is no `key: value` line"),
        (["note: &a x"], "an anchor, an alias or a tag"),
        (["note: @x"], "cannot be written plain"),
        (['note: "x" y'], "after the closing quote"),
    ]:
        try:
            asks.read_back(with_answer(text, "Q1", lines))
        except AskError as e:
            assert says in str(e), (lines, str(e))
        else:
            raise AssertionError(lines)
    for doc, says in [
        ("```decision id=D1\noptions:\n  - a\n", "a fence opened with ``` is not closed"),
        ("```Decision id=D1\nproposal: x\n```\n", "is a fault to Pilot"),
        ("```decision\nproposal: x\n```\n", "a decision block without `id=<id>`"),
        ("```x id=D1\n```\n", "is a fault to Pilot"),
        ("```question id=Q1\n```\n```question id=Q1\n```\n", "a second block Q1"),
    ]:
        try:
            asks.read_back(doc)
        except AskError as e:
            assert says in str(e), (doc, str(e))
        else:
            raise AssertionError(doc)


def test_hand_written_answer_lines_read_back():
    """The fallback: the operator writes the answer lines into the file."""
    store = asks.new_store("By hand")
    asks.append(store, "question", "Q", "Body.", default="x")
    text = asks.render(store)
    for lines, value in [
        (["note: plain words   # a comment"], "plain words"),
        (["note: plain words", "  go on here", "", "  and here"],
         "plain words go on here\nand here"),
        (['note: "folded', '  lines \\', '  joined"'], "folded lines joined"),
        (["note: 'single", "", "  with a gap'"], "single\nwith a gap"),
        (["note: |4", "    kept", "     indented"], "kept\n indented"),
        (["note: |2", "    kept"], "kept"),
        (["note: |+", "    kept", ""], "kept"),
        (["note: #only a comment"], None),
        (["note:"], None),
        (['note: "  "'], None),
    ]:
        read = asks.read_back(with_answer(text, "Q1", lines))["Q1"]["lines"]
        assert read.get("note") == value, (lines, read)


def test_the_read_back_passes_over_code_and_reads_an_indented_fence():
    doc = "\n".join([
        "---", "title: '```decision id=D9'", "---", "",
        "````markdown", "```decision id=D8", "proposal: an example, quoted", "```", "````",
        "", "```python", "x = 1", "```", "",
        "  ```question id=Q1", "  default: d", "  answer: Yes", "  ```", ""])
    assert asks.read_back(doc) == {"Q1": {"kind": "question", "line": 15,
                                          "lines": {"answer": "Yes"}}}


# ---------------------------------------------------------------- the store and its checks

def test_render_refuses_what_pilot_would_refuse():
    cases = [
        (lambda s: s["entries"].append(dict(s["entries"][0])), "two asks with the id D1"),
        (lambda s: s["entries"][0].update(recommend="Rack"),
         "`recommend: Rack` names no option"),
        (lambda s: s["entries"][1].update(options=[{"label": "a"}]),
         "`options` or `recommend` beside `proposal`"),
        (lambda s: s["entries"][2].update(options=[{"label": "a"}]),
         "a question takes no `options`"),
        (lambda s: s["entries"][0].update(body="Text.\n\n## A heading"), "holds a heading"),
        (lambda s: s["entries"][0].update(body="```question id=Q9\n```"), "holds a block"),
        (lambda s: s["entries"][0].update(body="```python\nx = 1"), "does not close"),
        (lambda s: s["context"].append("# Heading"), "context paragraph 2 holds a heading"),
        (lambda s: s.pop("summary"), "a document of more than one ask has a `summary`"),
        (lambda s: s.update(title="Which layout the phone gets"),
         "the first ask's headline repeats the title"),
        (lambda s: s["entries"].clear(), "no ask"),
        (lambda s: s["entries"][4].update(due="deploy"), "`due` is one of"),
        (lambda s: s["entries"][2].update(due="test"), "a question takes no `due`"),
        (lambda s: s["entries"][0].update(headline="Use C #"), "ends in `#`"),
        (lambda s: s["entries"][0]["options"].append({"label": " Tabs "}),
         "two options with the label `Tabs`"),
        (lambda s: s["entries"][0]["options"].append({"label": "a\nb"}),
         "an option's label is more than one line"),
        (lambda s: s["entries"][0].update(colour="red"), "no field `colour`"),
        (lambda s: s["entries"][3].update(default="a\x00b"), "holds a NUL"),
        (lambda s: s.update(title=""), "the title is empty"),
        (lambda s: s["entries"][1].pop("proposal"),
         "a decision carries `options` or a `proposal`"),
    ]
    for change, says in cases:
        store = every_kind()
        change(store)
        try:
            asks.render(store)
        except AskError as e:
            assert says in str(e), (says, str(e))
        else:
            raise AssertionError(says)


def test_one_ask_renders_no_summary_and_needs_none():
    store = asks.new_store("One ask", summary="Not shown on one ask")
    asks.append(store, "question", "Who owns the copy", "Nobody is named.")
    text = asks.render(store)
    assert text.startswith("---\ntitle: One ask\n---\n\n## Who owns the copy\n")
    assert "summary" not in text


def test_append_numbers_by_the_kinds_letter_and_refuses_a_taken_id():
    store = asks.new_store("Ids")
    assert [asks.append(store, k, "H", "B.", **f) for k, f in [
        ("decision", {"proposal": "p"}), ("question", {}), ("decision", {"proposal": "p"}),
        ("action", {})]] == ["D1", "Q1", "D2", "A1"]
    assert asks.append(store, "decision", "H", "B.", id="R7", proposal="p") == "R7"
    for kwargs, says in [({"id": "D2"}, "holds an ask D2 already"),
                         ({"id": "a b"}, "is not letters, digits")]:
        try:
            asks.append(store, "decision", "H", "B.", proposal="p", **kwargs)
        except AskError as e:
            assert says in str(e), str(e)
        else:
            raise AssertionError(says)
    assert len(store["entries"]) == 5


def test_amend_replaces_fields_keeps_id_and_kind_and_leaves_a_refused_ask_alone():
    store = every_kind()
    asks.amend(store, "D1", options="", recommend="", proposal="keep it stacked")
    entry = store["entries"][0]
    assert (entry["id"], entry["kind"], entry["proposal"]) == ("D1", "decision",
                                                               "keep it stacked")
    assert "options" not in entry and "recommend" not in entry
    before = json.dumps(store)
    for fields, says in [({"recommend": "Nope"}, "`recommend` with no options"),
                         ({"kind": "question"}, "amend changes no kind"),
                         ({"headline": ""}, "the headline is empty")]:
        try:
            asks.amend(store, "D1", **fields)
        except AskError as e:
            assert says in str(e), str(e)
        else:
            raise AssertionError(says)
    assert json.dumps(store) == before
    asks.amend_frame(store, summary="", step="t9", for_="ada")
    assert ("summary" not in store, store["step"], store["for"]) == (True, "t9", "ada")


def test_a_note_is_a_paragraph_with_a_run_in_head_and_a_value_of_lines_a_literal_block():
    store = asks.new_store("Notes")
    asks.append(store, "decision", "Card it", "Out of scope.", proposal="a\n```\nb")
    asks.note(store, "D1", "plan-reviewer", "It recurs in P3.", date="2026-10-30")
    assert asks.render(store).endswith(
        "## Card it\n\nOut of scope.\n\n**plan-reviewer, 2026-10-30.** It recurs in P3.\n\n"
        "```decision id=D1\nproposal: |\n    a\n    ```\n    b\n```\n")
    try:
        asks.note(store, "D1", "x", "## heading", date="2026-10-30")
    except AskError as e:
        assert "a note holds a heading" in str(e)
    else:
        raise AssertionError("a heading in a note")


def test_render_file_writes_beside_the_store_and_never_over_an_answered_document():
    with tempfile.TemporaryDirectory() as tmp:
        path = asks.create(scratch_slice(tmp), "requirements", "Requirements")
        with asks.editing(path) as store:
            asks.append(store, "question", "Who owns the copy", "Nobody is named.")
        doc = asks.render_file(path)
        assert doc == path.with_suffix(".md") and doc.read_text() == asks.render(
            asks.load(path))
        assert asks.render_file(doc) == doc            # unanswered: rendered again
        doc.write_text(with_answer(doc.read_text(), "Q1", ["answer: Ada", "by: bob"]))
        try:
            asks.render_file(path)
        except AskError as e:
            assert "carries answers (Q1)" in str(e), str(e)
        else:
            raise AssertionError("rendered over an answered document")
        assert asks.absorb_file(doc) == ["Q1  answered by bob: Ada"]
        assert asks.load(path)["entries"][0]["answer_lines"] == {"answer": "Ada",
                                                                 "by": "bob"}


def test_next_path_numbers_after_every_file_in_asks():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = scratch_slice(tmp)
        assert asks.next_path(slice_dir, "requirements").name == "1-requirements.json"
        (slice_dir / "asks").mkdir()
        (slice_dir / "asks" / "2-plan-questions.md").write_text("")
        assert asks.next_path(slice_dir, "x").name == "3-x.json"
        try:
            asks.next_path(slice_dir, "Bad Slug")
        except AskError as e:
            assert "lower-case words" in str(e)
        else:
            raise AssertionError("a bad slug")


def test_store_of_resolves_a_document_to_its_store():
    assert asks.store_of("/s/asks/1-r.md") == Path("/s/asks/1-r.json")
    assert asks.store_of("/s/asks/1-r.json") == Path("/s/asks/1-r.json")
    assert asks.document_of("/s/asks/1-r.json") == Path("/s/asks/1-r.md")


# ---------------------------------------------------------------- the CLI

def test_the_cli_writes_renders_and_absorbs_a_document():
    with tempfile.TemporaryDirectory() as tmp:
        slice_dir = scratch_slice(tmp)
        code, out, err = run_cli("init", slice_dir, "requirements", "--title", "Requirements",
                                 "--summary", "What slice 031 builds", "--step", "t2",
                                 "--context", "-", stdin="The slice adds the layout.\n")
        assert code == 0, err
        store = Path(out.strip())
        assert store == slice_dir / "asks" / "1-requirements.json"
        code, out, err = run_cli("append", store, "--kind", "decision", "--headline",
                                 "Which layout the phone gets", "--body", "-",
                                 "--option", "Stacked", "one column", "--option", "Tabs",
                                 "--recommend", "Stacked", stdin="Two are possible.\n")
        assert (code, out) == (0, "D1\n"), err
        code, out, err = run_cli("append", store, "--kind", "action", "--headline",
                                 "Restart the store", "--body", "It is stale.", "--due",
                                 "test", "--check", "env pilot-store running")
        assert (code, out) == (0, "A1\n"), err
        code, out, err = run_cli("note", store, "D1", "--by", "plan-preparer", "--text",
                                 "Tabs hide the timeline.", "--date", "2026-10-30")
        assert (code, out) == (0, "D1 noted\n"), err
        code, out, err = run_cli("render", store.with_suffix(".md"))
        assert (code, out) == (0, f"{store.with_suffix('.md')}\n"), err
        text = store.with_suffix(".md").read_text()
        assert "  - Stacked: one column\n  - Tabs\nrecommend: Stacked\n" in text
        assert "**plan-preparer, 2026-10-30.** Tabs hide the timeline." in text
        assert "due" not in text
        store.with_suffix(".md").write_text(with_answer(
            with_answer(text, "D1", ["answer: Tabs", "by: ada", "at: 2026-10-30T10:00:00Z"]),
            "A1", ["done: 2026-10-30T11:00:00Z", "by: ada"]))
        code, out, err = run_cli("absorb", store.with_suffix(".md"))
        assert (code, out) == (0, "D1  answered by ada: Tabs\nA1  done by ada\n"), err
        code, out, err = run_cli("list", store)
        assert out == ("D1  decision  Which layout the phone gets  [answered by ada: Tabs]\n"
                       "A1  action  Restart the store  [done by ada]\n"), out
        code, out, err = run_cli("show", store, "A1")
        assert out.startswith("A1 — action, done by ada, due before the test\n"
                              "## Restart the store\n"), out
        assert "check: env pilot-store running\ndone: 2026-10-30T11:00:00Z\nby: ada\n```" \
            in out, out


def test_the_cli_amends_clears_and_refuses_with_exit_2():
    with tempfile.TemporaryDirectory() as tmp:
        store = asks.create(scratch_slice(tmp), "requirements", "Requirements",
                            summary="S", step="t2")
        assert run_cli("append", store, "--kind", "decision", "--headline", "H", "--body",
                       "B.", "--option", "a", "--option", "b", "--recommend", "a")[0] == 0
        code, out, err = run_cli("amend", store, "D1", "--clear", "options", "--clear",
                                 "recommend", "--proposal", "do a")
        assert (code, out) == (0, "D1 amended\n"), err
        assert asks.load(store)["entries"][0]["proposal"] == "do a"
        code, out, err = run_cli("amend", store, "--clear", "step", "--title", "New")
        assert (code, out) == (0, "the document amended\n"), err
        assert "step" not in asks.load(store) and asks.load(store)["title"] == "New"
        for argv, says in [
            (("amend", store, "--proposal", "x"), "amended with its id"),
            (("amend", store, "D1", "--title", "x"), "amended with no id"),
            (("amend", store, "D1", "--clear", "summary"), "amended with no id"),
            (("append", store, "--kind", "decision", "--headline", "H", "--body", "B."),
             "a decision carries `options` or a `proposal`"),
            (("append", store, "--kind", "question", "--headline", "H", "--body", "B.",
              "--option", "a", "b", "c"), "at most one line of text"),
            (("append", store, "--kind", "action", "--headline", "H", "--body", "-",
              "--proposal", "-"), "only one argument reads stdin"),
            (("absorb", Path(tmp) / "none.md"), "cannot be read"),
            (("list", Path(tmp) / "none.json"), "does not exist"),
        ]:
            code, out, err = run_cli(*argv, stdin="x")
            assert code == 2 and err.startswith("Error: ") and says in err, (argv, err)


def test_the_docstring_lists_every_verb():
    listed = re.findall(r"^  ([a-z]+) {2,}", asks.__doc__, re.M)
    parser = asks.build_parser()
    verbs = next(a for a in parser._actions if a.dest == "command").choices
    assert listed == list(verbs), (listed, list(verbs))


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
