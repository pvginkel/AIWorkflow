"""Tests for labeller_records — the run records as the labeller reads them.

Every data folder is a temp dir built from small invented records: state files, `slice.json`,
gate and sweep records and a groups file, in the places `runner-state.md` § The run records
gives. Nothing reads or writes the real home, except the one test that copies a real record,
when the home has it, into a temp dir and checks only its shape.

Run: `python3 ${CLAUDE_PLUGIN_ROOT}/tools/test_labeller_records.py` or via pytest.
"""

import contextlib
import copy
import importlib.util
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "labeller_records", Path(__file__).resolve().parent / "labeller_records.py"
)
lr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lr)

SPEC = "FooSpecs"
GROUPS = """# hand-edited
spec_repo = "FooSpecs"
repo = "Foo"
environment = "someone-foo"

[[project]]
name = "First"
summary = "the first group"
slices = ["002_two", "001_one"]
"""


def ts(minute: int, second: int = 0) -> str:
    return f"2026-11-01T10:{minute:02d}:{second:02d}+01:00"


def row(minute, role, rnd=1, outcome="done", phase=None, session=None, **kw) -> dict:
    out = {"ts": ts(minute), "phase": phase, "role": role, "round": rnd, "outcome": outcome,
           "summary": "invented", "session": session,
           "transcript": f"/home/x/.claude/projects/-work-Foo/{session}.jsonl" if session
           else None, "duration_s": 60}
    out.update(kw)
    return out


def run_state(history, **kw) -> dict:
    out = {"slice": "001_one", "created_at": ts(0), "updated_at": ts(59),
           "plugin_version": "0.10.80", "orchestrator": {"session": "orch-run", "transcript": "x"},
           "run_phase": "done", "known_phases": ["1", "2"], "appended_phases": [],
           "phases": {"1": {"status": "merged", "target": "backend",
                            "landed": {"root": "/work/Foo", "base": "a", "head": "b"}},
                      "2": {"status": "merged", "target": "backend"}},
           "progress": [{"code": "P1.code", "label": "P1 · The first thing", "state": "done"}],
           "in_flight": None, "exit": {"code": 0, "ts": ts(58)}, "history": history}
    out.update(kw)
    return out


def plan_state(history, **kw) -> dict:
    out = {"slice": "001_one", "created_at": "2026-11-01T09:00:00+01:00", "phase": "done",
           "orchestrator": {"session": "orch-plan", "transcript": "x"},
           "exit": {"code": 0, "ts": "2026-11-01T09:40:00+01:00"}, "history": history}
    out.update(kw)
    return out


PLAN_HISTORY = [
    {"ts": "2026-11-01T09:10:00+01:00", "role": "plan-writer", "round": 1, "outcome": "done",
     "session": "pw-1", "duration_s": 300},
    {"ts": "2026-11-01T09:20:00+01:00", "role": "plan-reviewer", "round": 1,
     "outcome": "issues", "session": "pr-1", "duration_s": 300},
    {"ts": "2026-11-01T09:30:00+01:00", "role": "plan-writer", "round": 2, "outcome": "done",
     "session": "pw-2", "duration_s": 300, "kind": "review-fix"},
    {"ts": "2026-11-01T09:35:00+01:00", "role": "plan-reviewer", "round": 2, "outcome": "go",
     "session": "pr-2", "duration_s": 120},
]

RUN_HISTORY = [
    row(5, "code-writer", 1, "done", "1", "cw-1", kind="first"),
    row(6, "gate", 1, "red", "1"),
    row(8, "test-fixer", 1, "clean", "1", "tf-1"),
    row(10, "code-writer", 2, "done", "1", "cw-2", kind="gate-fix"),
    row(11, "gate", 2, "green", "1"),
    row(13, "code-reviewer", 1, "issues", "1", "cr-1",
        findings=[{"id": "F1"}, {"id": "F2"}]),
    row(15, "code-writer", 3, "done", "1", "cw-3", kind="review-fix"),
    row(16, "gate", 3, "green", "1"),
    row(18, "code-reviewer", 2, "signoff", "1", "cr-2", findings=[]),
    row(20, "code-writer", 1, "question", "2", "cw-4", kind="first"),
    row(22, "code-writer", 1, "done", "2", "cw-5", kind="first"),
    row(23, "gate", 1, "green", "2"),
    row(25, "code-reviewer", 1, "signoff", "2", "cr-3"),
    row(27, "sweep", 1, "red", None),
    row(29, "test-fixer", 1, "clean", None, "tf-2"),
    row(31, "sweep", 2, "green", None),
    row(33, "consult", 1, "complete", None, "co-1", site="completion"),
    row(36, "test-agent", 1, "clean", None, "ta-1"),
    row(40, "doc-writer", 1, "done", None, "dw-1"),
    row(45, "wrap-up", 1, "done", None, "wu-1", kind="first"),
    row(46, "doc-gate", 1, "green", None),
]

SLICE_JSON = {"slice": "001_one", "card": "FOO-7", "title": "001 — The one",
              "plan": {"phases": 2, "acceptance_criteria": 5},
              "close_out": {"entries": 4, "fixed": 1, "carded": 1, "closed": 2},
              "code_review_findings": {"2": {"1": [{"id": "F1"}, {"id": "F2"}, {"id": "F3"}]}},
              "updated_at": ts(0), "plugin_version": "0.10.80"}


def write(path: Path, doc) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(doc if isinstance(doc, str) else json.dumps(doc))


def slice_dir(data: Path, slug: str = "001_one", spec: str = SPEC) -> Path:
    return data / "runs" / spec / slug


def build(data: Path, slug="001_one", run=None, plan=None, facts=None, spec=SPEC) -> Path:
    d = slice_dir(data, slug, spec)
    if run is not None:
        write(d / "state.json", run)
    if plan is not None:
        write(d / "plan_state.json", plan)
    if facts is not None:
        write(d / "slice.json", facts)
    return d


@contextlib.contextmanager
def data_folder(full=True):
    with tempfile.TemporaryDirectory() as tmp:
        data = Path(tmp) / "data"
        data.mkdir()
        if full:
            build(data, run=run_state(copy.deepcopy(RUN_HISTORY)),
                  plan=plan_state(copy.deepcopy(PLAN_HISTORY)), facts=SLICE_JSON)
            write(data / "groups" / f"{SPEC}.toml", GROUPS)
        yield data


def load(data: Path, blob=None):
    return lr.Records.load(data, blob)


def conv(sid, sessions=(), documents=()) -> dict:
    return {"session_id": sid, "sessions": list(sessions), "documents": list(documents),
            "transcripts": []}


MAIN = {"agent_id": None}
K = f"{SPEC}/001_one"


# ---------------------------------------------------------------- the index and its blob

def test_a_missing_data_folder_is_empty_records():
    with tempfile.TemporaryDirectory() as tmp:
        records, blob = load(Path(tmp) / "absent")
        assert records.slices == {} and records.groups() == []
        assert isinstance(blob, str)


def test_the_blob_reads_nothing_again_when_nothing_changed():
    with data_folder() as data:
        _, blob = load(data)
        records, again = load(data, blob)
        assert again is blob
        assert records.unit_rows([K])[0]["title"] == "001 — The one"


def test_a_changed_file_is_read_again_and_the_rest_kept():
    with data_folder() as data:
        _, blob = load(data)
        facts = dict(SLICE_JSON, title="001 — Renamed")
        path = slice_dir(data) / "slice.json"
        write(path, facts)
        os.utime(path, ns=(1, 1))
        records, again = load(data, blob)
        assert again != blob
        assert records.unit_rows([K])[0]["title"] == "001 — Renamed"


def test_a_stale_foreign_or_broken_blob_is_rebuilt():
    with data_folder() as data:
        fresh, blob = load(data)
        want = fresh.stage_rows(f"{K}|run")
        prefix = blob.split(":", 2)
        for bad in ("garbage", f"{prefix[0]}:0.0.0:{prefix[2]}", f"{prefix[0]}:{prefix[1]}:!!",
                    None, 42):
            records, again = load(data, bad)
            assert records.stage_rows(f"{K}|run") == want
            assert again == blob
        with tempfile.TemporaryDirectory() as other:
            shutil.copytree(data, Path(other) / "data")
            records, again = load(Path(other) / "data", blob)
            assert again != blob and records.stage_rows(f"{K}|run") == want


def test_a_changed_file_keeps_the_slices_other_files_from_its_chunk():
    with data_folder() as data:
        fresh, blob = load(data)
        want = fresh.stage_rows(f"{K}|run")
        path = slice_dir(data) / "slice.json"
        write(path, dict(SLICE_JSON, title="001 — Renamed"))
        os.utime(path, ns=(1, 1))
        read, reduce = [], lr._reduce
        lr._reduce = lambda rel, p: read.append(rel) or reduce(rel, p)
        try:
            records, again = load(data, blob)
        finally:
            lr._reduce = reduce
        assert read == [f"runs/{K}/slice.json"]
        assert records.unit_rows([K])[0]["title"] == "001 — Renamed"
        assert records.stage_rows(f"{K}|run") == [
            dict(r, title="001 — Renamed") if r["key"] == K else r for r in want]


def test_a_broken_chunk_reads_the_slice_again_and_stamps_alike():
    with data_folder() as data:
        fresh, blob = load(data)
        want = fresh.stage_rows(f"{K}|run")
        stamp = stamp_of(fresh, "orch-run")
        head, *chunks = blob.split(".")
        broken = ".".join([head, *("!!" for _ in chunks)])
        records, _ = load(data, broken)
        assert stamp_of(records, "orch-run") == stamp
        assert records.stage_rows(f"{K}|run") == want


def test_stamps_read_no_chunk():
    with data_folder() as data:
        _, blob = load(data)
        records, _ = load(data, blob)
        opened, decode = [], lr._decode_chunk
        lr._decode_chunk = lambda c: opened.append(c) or decode(c)
        try:
            for sid in ("cw-1", "cw-5", "orch-run", "orch-plan", "nobody"):
                stamp_of(records, sid)
        finally:
            lr._decode_chunk = decode
        assert opened == []


def test_a_blob_past_the_cap_is_not_handed_back():
    with data_folder() as data:
        cap = lr.MAX_BLOB
        lr.MAX_BLOB = 100
        try:
            records, blob = load(data)
        finally:
            lr.MAX_BLOB = cap
        assert blob is None and records.slices


def test_a_half_written_file_counts_as_absent():
    with data_folder() as data:
        write(slice_dir(data, "002_two") / "state.json", "{not json")
        records, _ = load(data)
        assert records.unit_rows([f"{SPEC}/002_two"]) == []


def test_the_spec_repos_and_the_projects_rules():
    with data_folder() as data:
        write(data / "groups" / "BarSpecs.toml", 'spec_repo = "BarSpecs"\n')
        write(data / "projects" / "Foo.json",
              {"repo": "Foo", "file_classes": [{"class": "docs", "paths": ["notes/**"]}]})
        records, _ = load(data)
        assert records.spec_repos == {SPEC, "BarSpecs"}
        assert records.project_rules == {"Foo": [{"class": "docs", "paths": ["notes/**"]}]}


# ---------------------------------------------------------------- keys, kinds and nesting

def keys(records, stage="run"):
    return [r["key"] for r in records.stage_rows(f"{K}|{stage}")]


def test_the_keys_of_every_kind():
    with data_folder() as data:
        records, _ = load(data)
        ks = keys(records)
        assert ks[:2] == [K, f"{K}|run"]
        for want in (f"{K}|run|P1", f"{K}|run|P2", f"{K}|run|P1|code-writer|1",
                     f"{K}|run|P1|gate|1", f"{K}|run|P1|test-fixer|1",
                     f"{K}|run|P2|code-writer|1", f"{K}|run|P2|code-writer|1.2",
                     f"{K}|run|sweep|1", f"{K}|run|sweep|2", f"{K}|run|test-fixer|1",
                     f"{K}|run|consult|1", f"{K}|run|doc-gate|1", f"{K}|run|wrap-up|1"):
            assert want in ks, want
        assert keys(records, "plan")[2:] == [f"{K}|plan|plan-writer|1",
                                             f"{K}|plan|plan-reviewer|1",
                                             f"{K}|plan|plan-writer|2",
                                             f"{K}|plan|plan-reviewer|2"]


def test_every_unit_stands_after_its_part_of_and_its_occasion():
    with data_folder() as data:
        records, _ = load(data)
        rows = records.stage_rows(f"{K}|run")
        seen = set()
        kinds = {r["key"]: r["kind"] for r in rows}
        nest = {("stage", "slice"), ("phase", "stage"), ("dispatch", "phase"),
                ("dispatch", "stage"), ("sweep", "stage"), ("gate", "phase"), ("gate", "stage")}
        for r in rows:
            for k in (r["part_of"], r["occasioned_by"]):
                assert k is None or k in seen, (r["key"], k)
            if r["part_of"]:
                assert (r["kind"], kinds[r["part_of"]]) in nest
            seen.add(r["key"])
        assert len(seen) == len(rows)


def test_a_running_rounds_key_is_the_one_its_row_takes():
    with data_folder() as data:
        history = copy.deepcopy(RUN_HISTORY[:10])
        inflight = {"phase": "2", "role": "code-writer", "round": 1, "session": "cw-5",
                    "started_at": ts(20, 30), "kind": "first"}
        build(data, run=run_state(history, in_flight=inflight, run_phase="phases", exit=None))
        records, _ = load(data)
        running = records.unit_rows([f"{K}|run|P2|code-writer|1.2"])[-1]
        assert running["ended_at"] is None and running["outcome"] is None
        assert running["started_at"] == "2026-11-01T09:20:30.000000Z"
        build(data, run=run_state(copy.deepcopy(RUN_HISTORY[:11])))
        records, _ = load(data)
        landed = records.unit_rows([f"{K}|run|P2|code-writer|1.2"])[-1]
        assert landed["outcome"] == "done" and landed["ended_at"] is not None


def test_the_task_runners_tasks_are_phases():
    with data_folder() as data:
        run = run_state([row(5, "code-writer", 1, "done", None, "t-cw", task="01_first")],
                        phase="done", tasks={"01_first": {"status": "merged"}})
        for k in ("run_phase", "phases", "known_phases"):
            run.pop(k)
        build(data, "003_three", run=run)
        records, _ = load(data)
        rows = records.stage_rows(f"{SPEC}/003_three|run")
        assert [r["key"].split("|", 1)[1] for r in rows[2:]] == [
            "run|P01_first", "run|P01_first|code-writer|1"]
        assert rows[1]["outcome"] == "done"
        assert not records.adopted(f"{SPEC}/003_three")


# ---------------------------------------------------------------- attributes

def unit(records, key):
    return records.unit_rows([key])[-1]


def test_the_titles_variants_and_card():
    with data_folder() as data:
        records, _ = load(data)
        assert unit(records, K)["card"] == "FOO-7"
        assert unit(records, f"{K}|run")["title"] == "Run"
        assert unit(records, f"{K}|run")["variant"] == "run"
        assert unit(records, f"{K}|run|P1")["title"] == "P1 · The first thing"
        assert unit(records, f"{K}|run|P2")["title"] == "P2"
        cw = unit(records, f"{K}|run|P1|code-writer|3")
        assert (cw["title"], cw["variant"], cw["role"], cw["round"]) == (
            "code-writer 3", "review-fix", "code-writer", 3)
        assert unit(records, f"{K}|run|consult|1")["variant"] == "completion"
        assert unit(records, f"{K}|run|sweep|2")["title"] == "Gate sweep 2"
        gate = unit(records, f"{K}|run|P1|gate|1")
        assert (gate["kind"], gate["title"], gate["variant"]) == ("gate", "Gate 1", "gate")


def test_a_slice_with_no_title_is_named_by_its_folder():
    with data_folder() as data:
        build(data, "004_four", run=run_state([]))
        records, _ = load(data)
        assert unit(records, f"{SPEC}/004_four")["title"] == "004_four"
        assert unit(records, f"{SPEC}/004_four")["card"] is None


def test_the_times():
    with data_folder() as data:
        records, _ = load(data)
        cw = unit(records, f"{K}|run|P1|code-writer|1")
        # no started_at: ts less duration_s
        assert (cw["started_at"], cw["ended_at"]) == ("2026-11-01T09:04:00.000000Z",
                                                      "2026-11-01T09:05:00.000000Z")
        p1 = unit(records, f"{K}|run|P1")
        assert p1["started_at"] == cw["started_at"]
        assert p1["ended_at"] == "2026-11-01T09:18:00.000000Z"
        run = unit(records, f"{K}|run")
        assert (run["started_at"], run["ended_at"]) == ("2026-11-01T09:00:00.000000Z",
                                                        "2026-11-01T09:58:00.000000Z")
        sl = unit(records, K)
        assert sl["started_at"] == "2026-11-01T08:00:00.000000Z"
        assert sl["ended_at"] == run["ended_at"] and sl["outcome"] == "done"


def test_an_unfinished_stage_has_no_end():
    with data_folder() as data:
        build(data, run=run_state(copy.deepcopy(RUN_HISTORY[:5]), run_phase="phases",
                                  exit=None,
                                  phases={"1": {"status": "in_progress"},
                                          "2": {"status": "pending"}}))
        records, _ = load(data)
        for key in (K, f"{K}|run", f"{K}|run|P1"):
            assert unit(records, key)["ended_at"] is None
            assert unit(records, key)["outcome"] is None


def test_the_outcomes_fold_where_alike():
    """D5: a word meaning one of the six takes it; the driver's other words are their own."""
    with data_folder() as data:
        records, _ = load(data)
        got = {k: unit(records, f"{K}|{k}")["outcome"] for k in (
            "run|P1|code-writer|1", "run|P1|gate|1", "run|P1|gate|2", "run|P1|code-reviewer|1",
            "run|P1|code-reviewer|2", "run|P2|code-writer|1", "run|sweep|1",
            "run|test-fixer|1", "run|consult|1", "run|test-agent|1", "plan|plan-reviewer|2",
            "run|doc-gate|1")}
        assert got == {"run|P1|code-writer|1": "done", "run|P1|gate|1": "red",
                       "run|P1|gate|2": "green", "run|P1|code-reviewer|1": "issues",
                       "run|P1|code-reviewer|2": "signoff", "run|P2|code-writer|1": "question",
                       "run|sweep|1": "red", "run|test-fixer|1": "done",
                       "run|consult|1": "complete", "run|test-agent|1": "done",
                       "plan|plan-reviewer|2": "signoff", "run|doc-gate|1": "green"}
    out = lr._Units._outcome
    for word, want in (("go", "signoff"), ("questions", "question"), ("clean", "done"),
                       ("findings", "issues"), ("critical", "issues"), ("blocked", "blocked"),
                       ("session_limit", "session_limit"), ("nothing_ran", "nothing_ran"),
                       ("amend", "amend"), ("proceed", "proceed"), ("merge", "merge"),
                       ("unheard_of", None), (None, None)):
        assert out({"role": "any", "outcome": word}) == want, word
    import labeller_vocab
    codes = [v["code"] for v in labeller_vocab.lists()["unit_outcome"]]
    assert codes[:6] == ["done", "signoff", "issues", "red", "green", "question"]
    assert not set(lr.FOLDED_OUTCOMES) - set(codes[:6]) - {"clean", "go", "critical",
                                                            "findings", "questions"}
    assert set(lr.FOLDED_OUTCOMES.values()) <= set(codes[:6])
    assert not set(codes[6:]) & set(lr.FOLDED_OUTCOMES)


def test_rework_kind():
    with data_folder() as data:
        records, _ = load(data)
        rk = {r["key"].split("|", 1)[1]: r["rework_kind"]
              for r in records.stage_rows(f"{K}|run") if r["kind"] == "dispatch"}
        assert rk["run|consult|1"] == "consult"
        assert rk["run|P1|code-writer|1"] is None
        assert rk["run|P1|code-writer|2"] == "rework"
        assert rk["run|P1|code-reviewer|2"] == "rework"
        assert rk["run|P2|code-writer|1.2"] is None        # round 1
        assert all(r["rework_kind"] is None for r in records.stage_rows(f"{K}|plan"))
        assert all(r["rework_kind"] is None for r in records.stage_rows(f"{K}|run")
                   if r["kind"] in ("gate", "sweep"))


def test_a_continuation_an_appended_phase_and_a_consult_with_no_site():
    with data_folder() as data:
        history = [row(1, "code-writer", 1, "question", "1", "a"),
                   row(2, "code-writer", 2, "done", "1", "b"),
                   row(3, "code-writer", 1, "done", "3", "c"),
                   row(4, "consult", 1, "proceed", "1", "d"),
                   row(5, "consult", 2, "complete", None, "e"),
                   row(6, "consult", 3, "complete", None, "f")]
        build(data, run=run_state(history, appended_phases=["3"]))
        records, _ = load(data)
        rk = {r["key"].split("|", 1)[1]: r["rework_kind"]
              for r in records.stage_rows(f"{K}|run") if r["kind"] == "dispatch"}
        assert rk == {"run|P1|code-writer|1": None, "run|P1|code-writer|2": None,
                      "run|P3|code-writer|1": "rework", "run|P1|consult|1": "rework",
                      "run|consult|2": "consult", "run|consult|3": "rework"}


def test_occasioned_by():
    with data_folder() as data:
        records, _ = load(data)
        occ = {r["key"].split("|", 1)[1]: (r["occasioned_by"] or "").split("|", 1)[-1] or None
               for r in [*records.stage_rows(f"{K}|run"), *records.stage_rows(f"{K}|plan")]
               if r["kind"] != "slice"}
        assert occ["run|P1|code-writer|1"] is None
        assert occ["run|P1|test-fixer|1"] == "run|P1|gate|1"
        assert occ["run|P1|code-writer|2"] == "run|P1|gate|1"
        assert occ["run|P1|code-writer|3"] == "run|P1|code-reviewer|1"
        assert occ["run|P2|code-writer|1.2"] == "run|P2|code-writer|1"
        assert occ["run|test-fixer|1"] == "run|sweep|1"
        assert occ["plan|plan-writer|2"] == "plan|plan-reviewer|1"
        assert occ["plan|plan-writer|1"] is None


def test_occasions_read_from_rows_with_no_kind():
    with data_folder() as data:
        history = [row(1, "code-writer", 1, "done", "1", "a"),
                   row(2, "code-reviewer", 1, "issues", "1", "b"),
                   row(3, "code-writer", 2, "done", "1", "c"),
                   row(4, "consult", 1, "proceed", "1", "d"),
                   row(5, "code-writer", 1, "question", "2", "e"),
                   row(6, "code-writer", 2, "done", "2", "f")]
        build(data, run=run_state(history))
        records, _ = load(data)
        occ = {r["key"].split("|", 1)[1]: r["occasioned_by"]
               for r in records.stage_rows(f"{K}|run") if r["kind"] == "dispatch"}
        assert occ["run|P1|code-writer|2"] == f"{K}|run|P1|code-reviewer|1"
        assert occ["run|P1|consult|1"] == f"{K}|run|P1|code-reviewer|1"
        assert occ["run|P2|code-writer|2"] == f"{K}|run|P2|code-writer|1"


def test_the_measures():
    with data_folder() as data:
        records, _ = load(data)

        def m(key):
            return {x["measure"]: x["amount"] for x in unit(records, key)["measures"]}

        assert m(K) == {"planned_phases": 2, "acceptance_criteria": 5}
        assert m(f"{K}|run") == {"close_out_entries": 4, "close_out_fixed": 1,
                                 "close_out_carded": 1, "close_out_closed": 2}
        assert m(f"{K}|plan") == {}
        assert m(f"{K}|run|P1|code-reviewer|1") == {"review_findings": 2}
        assert m(f"{K}|run|P1|code-reviewer|2") == {"review_findings": 0}
        assert m(f"{K}|run|P2|code-reviewer|1") == {"review_findings": 3}   # slice.json
        assert m(f"{K}|plan|plan-reviewer|1") == {}                         # not known
        assert m(f"{K}|run|P1|code-writer|1") == {}


def test_plan_review_findings_from_slice_json():
    with data_folder() as data:
        build(data, facts=dict(SLICE_JSON, plan_review_findings={"1": [{"id": "B1"}]}))
        records, _ = load(data)
        ms = unit(records, f"{K}|plan|plan-reviewer|1")["measures"]
        assert ms == [{"measure": "review_findings", "amount": 1}]


# ---------------------------------------------------------------- the driver's Test Runs

def test_the_driver_test_runs_wait_on_o4():
    with data_folder() as data:
        d = slice_dir(data)
        write(d / "gates" / "P1_gate_1.json",
              dict(row(6, "gate", 1, "red", "1"), started_at=ts(5, 30),
                   projects=[{"project": "backend", "cmd": "kc project test", "outcome": "red"},
                             {"project": "frontend", "outcome": "nothing_ran"},
                             {"project": "spec_check", "outcome": "green"}]))
        write(d / "sweeps" / "r1.json",
              {"run": 1, "ran_at": ts(27), "outcome": "red", "results": [
                  {"repo": "/work/Foo", "component": "backend", "verb": "test",
                   "outcome": "red", "duration_s": 30},
                  {"repo": "/work/Foo", "component": "backend", "verb": "lint",
                   "outcome": "green", "duration_s": 3},
                  {"repo": "/work/Foo", "component": "frontend", "verb": "test",
                   "outcome": "green", "duration_s": 0, "reused": "P2 gate r1"}]})
        records, _ = load(data)
        assert records.test_runs(f"{K}|run") == []
        runs = records.driver_test_runs(f"{K}|run")
        assert [(r["work_unit"].split("|", 1)[1], r["suite"], r["passed"]) for r in runs] == [
            ("run|P1|gate|1", "Foo/backend/test", False),
            ("run|sweep|1", "Foo/backend/test", False)]
        assert runs[0]["started_at"] == "2026-11-01T09:05:30.000000Z"
        assert runs[1]["started_at"] == "2026-11-01T09:26:30.000000Z"
        assert all(r["tests"] is None for r in runs)
        lr.DRIVER_TEST_RUNS = True
        try:
            assert len(records.test_runs(f"{K}|run")) == 2
        finally:
            lr.DRIVER_TEST_RUNS = False


# ---------------------------------------------------------------- ties

def test_a_dispatch_is_tied_by_its_rows_window():
    with data_folder() as data:
        history = copy.deepcopy(RUN_HISTORY)
        history[0]["session"] = history[9]["session"] = "same"   # two rounds, one session
        build(data, run=run_state(history))
        records, _ = load(data)
        tie = records.tie(conv("same"), MAIN)
        assert tie.rule == "dispatch" and tie.role == "code-writer" and not tie.is_anchor
        assert set(tie.units) == {f"{K}|run|P1|code-writer|1", f"{K}|run|P2|code-writer|1"}
        assert tie.unit_for("2026-11-01T09:04:30Z") == f"{K}|run|P1|code-writer|1"
        assert tie.unit_for("2026-11-01T09:12:00Z") == f"{K}|run|P2|code-writer|1"
        assert tie.unit_for("2026-11-01T08:00:00Z") == f"{K}|run|P1|code-writer|1"
        assert tie.unit_for("2026-11-01T12:00:00Z") is None


def test_a_running_round_ties_the_launch_after_every_row():
    with data_folder() as data:
        inflight = {"phase": "2", "role": "code-writer", "round": 1, "session": "cw-4",
                    "started_at": ts(21)}
        build(data, run=run_state(copy.deepcopy(RUN_HISTORY[:10]), in_flight=inflight,
                                  run_phase="phases", exit=None))
        records, _ = load(data)
        tie = records.tie(conv("cw-4"), MAIN)
        assert tie.unit_for("2026-11-01T09:19:30Z") == f"{K}|run|P2|code-writer|1"
        assert tie.unit_for("2026-11-01T09:21:10Z") == f"{K}|run|P2|code-writer|1.2"


def test_a_stage_session_is_its_stage_and_its_anchor():
    with data_folder() as data:
        records, _ = load(data)
        tie = records.tie(conv("orch-run"), MAIN)
        assert (tie.rule, tie.role, tie.anchors) == ("stage", "orchestrator:run", (f"{K}|run",))
        assert tie.unit_for("2026-11-01T09:30:00Z") == f"{K}|run"
        assert records.tie(conv("orch-plan"), MAIN).role == "orchestrator:plan"


def test_a_clarification_launch_is_the_slices():
    with data_folder() as data:
        records, _ = load(data)
        sessions = [{"id": "s1", "kind": "work", "created_at": "2026-11-01T09:00:00Z",
                     "brief": "/dev:run-slice 001_one", "repo": "Foo", "clarification": False},
                    {"id": "s2", "kind": "work", "created_at": "2026-11-01T09:30:00Z",
                     "brief": "clarify", "repo": "Foo", "clarification": True},
                    {"id": "s3", "kind": "work", "created_at": "2026-11-01T09:40:00Z",
                     "brief": "go on", "repo": "Foo", "clarification": False}]
        tie = records.tie(conv("orch-run", sessions), MAIN)
        assert tie.unit_for("2026-11-01T09:10:00Z") == f"{K}|run"
        assert tie.unit_for("2026-11-01T09:29:57Z") == K          # within the 5 s
        assert tie.unit_for("2026-11-01T09:45:00Z") == f"{K}|run"
        assert K in tie.units


def test_a_hand_run_stage_anchors_on_its_first_rows_session():
    with data_folder() as data:
        build(data, run=run_state(copy.deepcopy(RUN_HISTORY), orchestrator=None))
        records, _ = load(data)
        assert records.tie(conv("cw-1"), MAIN).anchors == (f"{K}|run",)
        assert records.tie(conv("cw-2"), MAIN).anchors == ()


def test_a_pilot_stage_before_its_loop_names_no_unit():
    with data_folder() as data:
        records, _ = load(data)
        sessions = [{"id": "s", "kind": "work", "created_at": "2026-11-01T09:00:00Z",
                     "brief": "/dev:plan-slice 009_nine", "repo": "Foo", "clarification": False}]
        tie = records.tie(conv("new-conv", sessions), MAIN)
        assert tie.units == () and tie.role == "orchestrator:plan"
        assert tie.unit_for("2026-11-01T09:00:00Z") is None


def test_a_sub_agent_carries_no_unit():
    with data_folder() as data:
        records, _ = load(data)
        tie = records.tie(conv("cw-1"), {"agent_id": "a1", "agent_type": "Explore"})
        assert tie.role == "subagent:Explore" and tie.units == () and tie.anchors == ()
        assert tie.slices == (K,) and tie.unit_for("2026-11-01T09:04:30Z") is None


def test_a_chat_or_unknown_session_ties_nothing():
    with data_folder() as data:
        records, _ = load(data)
        chat = [{"id": "c", "kind": "chat", "created_at": "2026-11-01T09:00:00Z",
                 "brief": "hello", "repo": "Foo", "clarification": False}]
        for c in (conv("chat-conv", chat), conv("someone")):
            tie = records.tie(c, MAIN)
            assert tie.units == () and tie.role is None and tie.adopted_group is None


# ---------------------------------------------------------------- the groups and adoption

def test_the_groups_and_their_keys():
    with data_folder() as data:
        for slug in ("002_two", "005_five"):
            build(data, slug, run=run_state([]), facts={"title": f"{slug} title"})
        records, _ = load(data)
        groups = records.groups()
        assert [(g["key"], g["name"], g["slices"]) for g in groups] == [
            (f"{SPEC}/001_one", "First", [f"{SPEC}/002_two", f"{SPEC}/001_one"]),
            (f"{SPEC}/005_five", "005_five title", [f"{SPEC}/005_five"])]
        assert groups[0]["summary"] == "the first group" and groups[0]["spec_repo"] == SPEC
        write(data / "groups" / f"{SPEC}.toml", GROUPS.replace('"First"', '"Renamed"')
              .replace('"001_one"]', '"001_one", "005_five"]'))
        records, _ = load(data)
        assert [(g["key"], g["name"]) for g in records.groups()] == [(f"{SPEC}/001_one",
                                                                      "Renamed")]


def test_a_slice_pilot_ran_or_a_task_runner_ran_is_not_adopted():
    with data_folder() as data:
        records, _ = load(data)
        assert records.adopted(K)
        assert records.tie(conv("cw-1"), MAIN).adopted_group == K
        records.use_pilot({"conversations": ["orch-run"]})
        assert not records.adopted(K) and records.groups() == []
        tie = records.tie(conv("cw-1"), MAIN)
        assert tie.adopted_group is None and tie.pilot


def test_a_spec_repo_with_no_groups_file_adopts_nothing():
    with data_folder() as data:
        build(data, run=run_state(copy.deepcopy(RUN_HISTORY)), spec="BarSpecs")
        records, _ = load(data)
        assert not records.adopted("BarSpecs/001_one")


def facts(prompt=None, cmd=None, entry="cli", cwd="/work/Foo", loops=(), cmds=None):
    return {"cwd": cwd, "entrypoint": entry, "first_prompt": prompt, "first_cmd": cmd,
            "cmds": cmds if cmds is not None else ([cmd] if cmd else []), "loops": list(loops)}


def test_r2_by_its_command_or_its_loop():
    with data_folder() as data:
        records, _ = load(data)
        named = records.named_from_facts(facts("/dev:run-slice 001", ["dev:run-slice", "001"]))
        assert named == [f"{SPEC}/001@run"]
        tie = records.tie(conv("old"), {"agent_id": None, "named": named})
        assert tie.unit_for(None) == f"{K}|run" and tie.adopted_group == K
        named = records.named_from_facts(facts("go", loops=[
            ["plan_loop", "run", "/work/FooSpecs/slices/001_one"],
            ["run_loop", "wait", "/work/FooSpecs/slices/001_one"]]))
        assert named == [f"{SPEC}/001_one@run"]
        named = records.named_from_facts(facts("/dev:plan-slice 007", ["dev:plan-slice", "007"],
                                               loops=[["plan_loop", "run", "001_one"]]))
        assert named == [f"{SPEC}/007", f"{SPEC}/001_one@plan"]


def test_r4_and_r3():
    with data_folder() as data:
        records, _ = load(data)
        named = records.named_from_facts(facts("Close out slice 001 now"))
        assert named == [f"{SPEC}/001@close-out"]
        tie = records.tie(conv("old"), {"agent_id": None, "named": named})
        assert tie.unit_for(None) == f"{K}|close-out"
        assert records.unit_rows([f"{K}|close-out"])[-1]["title"] == "Close out"
        named = records.named_from_facts(facts(
            "Execute phase P2 of /work/FooSpecs/slices/001_one", entry="sdk-cli"))
        assert named == [f"{SPEC}/001_one@run.P2"]
        tie = records.tie(conv("old"), {"agent_id": None, "named": named})
        assert tie.unit_for(None) == f"{K}|run|P2" and tie.role is None
        assert records.named_from_facts(facts("Hello there", entry="sdk-cli")) == []


def test_adoption_reads_no_session_pilot_or_the_records_know():
    with data_folder() as data:
        records, _ = load(data)
        f = facts("/dev:run-slice 001", ["dev:run-slice", "001"])
        assert records.needs_facts(conv("old"), MAIN)
        assert not records.needs_facts(conv("cw-1"), MAIN)
        assert not records.needs_facts(conv("old"), {"agent_id": "a"})
        session = [{"id": "s", "kind": "work", "created_at": "2026-11-01T09:00:00Z",
                    "brief": "do", "repo": "Foo", "clarification": False}]
        assert records.tie(conv("old", session), {"agent_id": None, "facts": f}).units == ()
        records.use_pilot(["old"])
        assert records.tie(conv("old"), {"agent_id": None, "facts": f}).units == ()


def test_a_name_of_a_slice_not_adopted_ties_nothing_but_stays_named():
    with data_folder() as data:
        records, _ = load(data)
        named = records.named_from_facts(facts("/dev:run-slice 042", ["dev:run-slice", "042"]))
        assert named == [f"{SPEC}/042"]
        tie = records.tie(conv("old"), {"agent_id": None, "named": named})
        assert tie.units == () and tie.named == (f"{SPEC}/042",)


def test_read_facts_on_an_invented_transcript():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "t.jsonl"
        lines = [
            {"type": "user", "cwd": "/work/Foo", "entrypoint": "cli",
             "message": {"content": "<command-name>/clear</command-name>"}},
            {"type": "user", "cwd": "/work/Foo", "entrypoint": "cli",
             "message": {"content": "<command-message>dev:run-slice</command-message>\n"
                                    "<command-name>/dev:run-slice</command-name>\n"
                                    "<command-args>001</command-args>"}},
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "Bash", "id": "t1", "input": {
                    "command": "cd /work/Foo && timeout 900 python3 \"/x/tools/run_loop.py\" "
                               "run /work/FooSpecs/slices/001_one --detach"}}]}},
            {"type": "user", "message": {"content": [
                {"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]}},
        ]
        path.write_text("".join(json.dumps(x, separators=(",", ":")) + "\n" for x in lines))
        got = lr.read_facts(path)
        assert got["cwd"] == "/work/Foo" and got["entrypoint"] == "cli"
        assert got["first_cmd"] == ["dev:run-slice", "001"]
        assert [x[:2] for x in got["loops"]] == [["run_loop", "run"]]
        assert "001_one" in got["loops"][0][2]


# ---------------------------------------------------------------- the stamp

def ctx(c, t, pilot=frozenset()):
    return {"conversation": c, "transcript": t, "pilot": pilot}


def stamp_of(records, sid, transcript=MAIN, sessions=()):
    c = conv(sid, sessions)
    tie = records.tie(c, transcript)
    return records.stamp(tie, ctx(c, transcript))


def test_a_rewrite_that_changes_no_derived_fact_changes_no_stamp():
    with data_folder() as data:
        records, blob = load(data)
        before = {s: stamp_of(records, s) for s in ("cw-1", "orch-run", "cr-1")}
        run = run_state(copy.deepcopy(RUN_HISTORY), updated_at=ts(59, 30),
                        driver={"pid": 4242, "host": "elsewhere"},
                        gate_greens=[{"repo": "Foo", "verb": "test"}])
        for h in run["history"]:
            h["summary"] = "reworded"
        path = slice_dir(data) / "state.json"
        write(path, run)
        os.utime(path, ns=(2, 2))
        records, again = load(data, blob)
        assert again != blob
        assert {s: stamp_of(records, s) for s in before} == before


def test_a_changed_unit_changes_the_stamp_of_every_transcript_naming_it():
    with data_folder() as data:
        records, _ = load(data)
        before = {s: stamp_of(records, s) for s in ("cw-1", "cw-5", "orch-run", "orch-plan")}
        sub = stamp_of(records, "cw-1", {"agent_id": "a1", "agent_type": "Explore"})
        run = run_state(copy.deepcopy(RUN_HISTORY))
        run["history"][0]["outcome"] = "blocked"      # P1's code-writer 1
        write(slice_dir(data) / "state.json", run)
        records, _ = load(data)
        after = {s: stamp_of(records, s) for s in before}
        assert after["cw-1"] != before["cw-1"]           # its own unit
        assert after["orch-run"] != before["orch-run"]   # the anchor: its whole stage
        assert after["cw-5"] == before["cw-5"]           # P2's: nothing above it changed
        assert after["orch-plan"] == before["orch-plan"]
        assert stamp_of(records, "cw-1", {"agent_id": "a1", "agent_type": "Explore"}) == sub


def test_the_stamp_follows_the_pilot_header_and_retakes_the_tie():
    with data_folder() as data:
        records, _ = load(data)
        c = conv("cw-1")
        tie = records.tie(c, MAIN)
        quiet = records.stamp_inputs(tie, ctx(c, MAIN))
        assert quiet["group"] == K and quiet["pilot"] is False
        tie = records.tie(c, MAIN)
        loud = records.stamp_inputs(tie, ctx(c, MAIN, frozenset({"orch-run"})))
        assert loud["group"] is None and loud["pilot"] is True
        assert tie.adopted_group is None and tie.pilot      # the caller's tie agrees


def test_a_named_tie_stamps_alike_from_the_file_and_from_the_held_stamp():
    with data_folder() as data:
        records, _ = load(data)
        f = facts("/dev:run-slice 001", ["dev:run-slice", "001"])
        c = conv("old")
        by_file = records.tie(c, {"agent_id": None, "facts": f})
        stamp = records.stamp(by_file, ctx(c, MAIN))
        assert stamp.endswith(f":{SPEC}/001@run")
        held = records.tie(c, {"agent_id": None, "held": stamp, "named": None})
        assert records.stamp(held, ctx(c, MAIN)) == stamp
        assert held.unit_for(None) == by_file.unit_for(None) == f"{K}|run"
        before = stamp
        build(data, facts=dict(SLICE_JSON, card="FOO-8"))
        records, _ = load(data)
        held = records.tie(c, {"agent_id": None, "named": [f"{SPEC}/001@run"]})
        assert records.stamp(held, ctx(c, MAIN)) != before


def test_a_new_spec_repo_changes_every_stamp():
    """D10 reads the spec repos for any transcript's `git add -A`, so every stamp covers them."""
    with data_folder() as data:
        records, _ = load(data)
        before = {s: stamp_of(records, s) for s in ("cw-1", "orch-run", "nobody")}
        build(data, "001_two", run=run_state([]), spec="BarSpecs")
        records, _ = load(data)
        after = {s: stamp_of(records, s) for s in before}
        assert all(after[s] != before[s] for s in before)


def test_stamp_inputs_are_json_and_small():
    with data_folder() as data:
        records, _ = load(data)
        for sid in ("cw-1", "orch-run", "nobody"):
            c = conv(sid)
            inputs = records.stamp_inputs(records.tie(c, MAIN), ctx(c, MAIN))
            assert len(json.dumps(inputs)) < 400


# ---------------------------------------------------------------- one real record's shape

REAL = Path.home() / ".claude/plugins/data/dev-aiworkflow/runs/SonosDisplaySpecs/001_now_playing"


def test_a_copy_of_a_real_record_reads_into_well_formed_units():
    """Reads a copy of one real record when the home has it (no fixture is committed) and
    checks only the shape: unique keys, every unit after what it points at, one anchor."""
    if not (REAL / "state.json").is_file():
        return
    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp) / "data" / "runs" / "SonosDisplaySpecs" / "001_now_playing"
        shutil.copytree(REAL, dest)
        records, blob = load(Path(tmp) / "data")
        key = "SonosDisplaySpecs/001_now_playing"
        rows = records.stage_rows(f"{key}|run")
        assert rows and rows[0]["key"] == key and blob
        seen = set()
        for r in rows:
            assert r["key"] not in seen
            assert r["part_of"] is None or r["part_of"] in seen
            assert r["occasioned_by"] is None or r["occasioned_by"] in seen
            seen.add(r["key"])
        assert {r["kind"] for r in rows} >= {"slice", "stage", "phase", "dispatch", "gate"}
        state = json.loads((dest / "state.json").read_text())
        orch = (state.get("orchestrator") or {}).get("session")
        if orch:
            assert records.tie(conv(orch), MAIN).anchors == (f"{key}|run",)


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
