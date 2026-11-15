"""The labeller's declared lists, as data: every list a label takes its value
from, the nestings of the Work Unit Kinds, and `declarations`, the digest of
what the `vocabularies` verb answers (docs/labeller.md § The vocabularies).

Every value is `{"code", "name", "description", "position"}` and the list's
extra facts beside them; `position` is the row's place in its list, from 1.
The rows below are in the page's order. Two lists are the classifier's own and
are read from `turn_profile`: `call_class` takes its codes and order from
TURN_CLASSES, `batchable_condition` its rows from BATCHABLE_WHYS.
"""

import base64
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# O8, open: whether a red gate counts among the error events. Until it is
# ruled the build gives no value; this is the one place to set it.
GATE_RED_IS_ERROR = None

# (code, name, description[, extra facts]) per list, in the page's order.
_WORK_UNIT_KIND = (
    ("slice", "Slice", "A slice: everything done for one folder of a spec repo."),
    ("stage", "Stage", "One stage of a slice: its planning, its run, or for an old slice "
                       "its triage or close-out."),
    ("phase", "Phase", "One phase of a slice's plan, from its first round to its merge."),
    ("dispatch", "Dispatch", "One dispatch of one role in one round, as the driver "
                             "recorded it."),
    ("sweep", "Sweep", "A loop-tail gate sweep the driver ran."),
    # O2, ruled: a driver's gate is a kind of its own, carried by the anchor.
    ("gate", "Gate", "A gate the driver ran: a phase's gate, or the doc, wrap-up or "
                     "fixes gate."),
)

# Each allowed pairing, inner ⊂ outer.
NESTING = (
    ("stage", "slice"),
    ("phase", "stage"),
    ("dispatch", "phase"),
    ("dispatch", "stage"),
    ("sweep", "stage"),
    ("gate", "phase"),
    ("gate", "stage"),
)

_UNIT_OUTCOME = (
    ("done", "Done", "The work ended as it should: a writer's round done, a phase merged, "
                     "a stage or slice finished."),
    ("signoff", "Signed off", "A review that found nothing blocking."),
    ("issues", "Issues", "A review that found something blocking."),
    ("red", "Red", "A gate or sweep that failed."),
    ("green", "Green", "A gate or sweep that passed."),
    ("question", "Question", "A writer that stopped on a question only the operator can "
                             "answer."),
)

_REWORK_KIND = (
    ("rework", "Rework", "Work done again: a second round, an appended phase, a consult "
                         "other than the completion consult."),
    ("consult", "Completion consult", "The completion consult, priced apart from rework."),
)

_UNIT_MEASURE = (
    ("planned_phases", "Planned phases",
     "The phases the plan held when it was done, less the ones the run appended.",
     {"unit": "phases"}),
    ("acceptance_criteria", "Acceptance criteria",
     "The items of the slice's `verification.json`.", {"unit": "criteria"}),
    ("review_findings", "Review findings", "The findings a review round reported.",
     {"unit": "findings"}),
    ("close_out_entries", "Close-out entries", "The entries of the slice's close-out report.",
     {"unit": "entries"}),
    ("close_out_fixed", "Close-out entries fixed", "Entries a change landed for.",
     {"unit": "entries"}),
    ("close_out_carded", "Close-out entries carded",
     "Entries handed on as a card or to another slice.", {"unit": "entries"}),
    ("close_out_closed", "Close-out entries closed", "Entries closed with no change.",
     {"unit": "entries"}),
)

_SEGMENT_KIND = (
    ("start", "Reading in", "Reading before the first change."),
    ("work", "Work", "The work itself."),
    ("gate", "Gate", "Running a gate: tests, lint, build."),
    ("records", "Records", "The done-record, the verdict and the commit."),
    ("wait", "Waiting", "Waiting on a command, a build or a background task."),
)

_WAIT_CAUSE = (
    ("command", "A command", "Its own foreground command ran."),
    ("sub_agent", "A sub-agent", "A sub-agent it dispatched ran."),
    ("background_task", "A background task", "It waited for a background task to end."),
    ("person", "A person", "It waited for a person's message."),
    ("hold", "A hold", "Pilot held it from running."),
    ("driver", "Its driver", "The loop that dispatched it started it again."),
    ("startup", "Startup", "Its process was starting."),
)

# The names and descriptions of turn_profile.TURN_CLASSES, by code; the list
# takes its codes and their order from TURN_CLASSES itself.
_CALL_CLASS = {
    "dispatch": ("Dispatch", "Started another session or a sub-agent."),
    "edit": ("Edit", "Changed a file of the work."),
    "gate": ("Gate", "Ran a test suite, a lint or a build."),
    "commit": ("Commit", "Changed git's state: a commit, a merge, a push."),
    "record": ("Record", "Wrote the run's own record, or handed back with no tool at its end."),
    "retry": ("Retry", "Ran again what failed in the two calls before."),
    "fumble": ("Fumble", "A tool call that failed."),
    "wait": ("Wait", "Waited on a command, a build or a background task."),
    "git-inspect": ("Git inspect", "Read git's state alone."),
    "orient-read": ("Orienting read", "Read before the session's first change."),
    "work-read": ("Working read", "Read after the first change, or a reviewer's reading."),
    "think": ("Think", "No tool, with nothing running."),
    "other": ("Other", "Anything else."),
}

_AVOIDABLE_KIND = (
    ("retry", "Retry", "Ran again what had just failed."),
    ("fumble", "Fumble", "A call that failed."),
    ("batchable", "Batchable", "A read that could have gone with the reads before it."),
)

_COMMAND_CLASS = (
    ("test_suite", "Test suite", "Runs a test suite."),
    ("gate", "Gate", "Runs a gate of the workflow's, or a lint or a build."),
    ("ci_wait", "CI wait", "Waits on a Jenkins build and its deploy."),
    ("chunked_wait", "Chunked wait",
     "A loop's or a long command's wait, in chunks under the cache's lifetime."),
    ("sleep_poll", "Sleep-poll", "Sleeps, and checks again."),
    ("git", "Git", "A git command."),
)

# Jenkins's words as the summary prints them; each one's name is its code.
_BUILD_RESULT = (
    ("SUCCESS", "SUCCESS", "The build passed."),
    ("FAILURE", "FAILURE", "The build failed."),
    ("ABORTED", "ABORTED", "The build was stopped."),
    ("UNSTABLE", "UNSTABLE", "The build ran with test failures."),
    ("NOT_BUILT", "NOT_BUILT", "The build did not run."),
)

_FILE_CLASS = (
    ("code", "Code", "What builds and runs the product, its configuration included.",
     {"counted": True}),
    ("test", "Tests", "Tests and their fixtures.", {"counted": True}),
    ("docs", "Docs", "A product repository's documentation.", {"counted": True}),
    ("spec", "Spec", "What a spec repo holds that was written.", {"counted": True}),
    ("generated", "Generated", "What a tool writes.", {"counted": False}),
    ("record", "Record", "What a run writes about itself in its slice's folder.",
     {"counted": False}),
)

_TOOL_EFFECT_KIND = (
    ("card_created", "Card created", "Created a card on the tracker."),
    ("card_updated", "Card updated", "Changed or commented on a card."),
    ("fieldnote_posted", "Fieldnote posted", "Posted a fieldnote."),
    ("document_registered", "Document registered", "Registered a document with Pilot."),
    ("push", "Push", "Pushed to a remote."),
)

_HOST_RULES = "/etc/claude-code/CLAUDE.md"
_RULE = (
    ("no_sleep_poll", "No sleep-poll",
     "Work that reports back is waited on by ending the turn, never by sleeping and "
     "checking.", {"home": _HOST_RULES}),
    ("no_git_add_all", "No `git add -A`", "Stage nothing until the commit, and commit by path.",
     {"home": _HOST_RULES}),
    ("no_tail_on_background_log", "No tail on a background log",
     "Never tail the log of a backgrounded command to see how far it got.",
     {"home": _HOST_RULES}),
)

_ASK_CATEGORY = (
    ("requirements", "Requirements", "The plan-preparer's requirements asks."),
    ("plan_question", "Plan question", "A question the planning put."),
    ("plan_review", "Plan review", "The plan review's findings put to the operator."),
    ("run_question", "Run question", "A question the run put."),
    ("close_out", "Close-out", "The slice's close-out report."),
    ("pilots_own", "Pilot's own", "A document Pilot itself put."),
)

_EVENT_KIND = (
    ("gate_red", "Gate red", "A gate or a test suite a session ran came back red.",
     {"is_error": GATE_RED_IS_ERROR}),
)

_CONTEXT_PART_KIND = (
    ("digest_section", "Digest section",
     "One section of the orientation digest the driver handed a dispatch."),
)


def _rows(spec) -> list[dict]:
    out = []
    for position, row in enumerate(spec, 1):
        code, name, description, *extra = row
        value = {"code": code, "name": name, "description": description,
                 "position": position}
        if extra:
            value.update(extra[0])
        out.append(value)
    return out


def _call_class() -> tuple:
    import turn_profile
    return tuple((code, *_CALL_CLASS[code]) for code in turn_profile.TURN_CLASSES)


def _batchable_condition() -> tuple:
    import turn_profile
    return tuple(turn_profile.BATCHABLE_WHYS)


def lists() -> dict[str, list[dict]]:
    """Every declared list, by its name (the record's reference entity)."""
    return {
        "work_unit_kind": _rows(_WORK_UNIT_KIND),
        "unit_outcome": _rows(_UNIT_OUTCOME),
        "rework_kind": _rows(_REWORK_KIND),
        "unit_measure": _rows(_UNIT_MEASURE),
        "segment_kind": _rows(_SEGMENT_KIND),
        "wait_cause": _rows(_WAIT_CAUSE),
        "call_class": _rows(_call_class()),
        "avoidable_kind": _rows(_AVOIDABLE_KIND),
        "batchable_condition": _rows(_batchable_condition()),
        "command_class": _rows(_COMMAND_CLASS),
        "build_result": _rows(_BUILD_RESULT),
        "file_class": _rows(_FILE_CLASS),
        "tool_effect_kind": _rows(_TOOL_EFFECT_KIND),
        "rule": _rows(_RULE),
        "ask_category": _rows(_ASK_CATEGORY),
        "event_kind": _rows(_EVENT_KIND),
        "context_part_kind": _rows(_CONTEXT_PART_KIND),
    }


def nesting() -> list[dict]:
    return [{"inner": inner, "outer": outer} for inner, outer in NESTING]


_CANONICAL = json.JSONEncoder(sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode


def canonical(value) -> str:
    """The canonical JSON every digest of the labeller's is taken over."""
    return _CANONICAL(value)


def digest(value) -> str:
    """22 characters of url-safe base64 of the sha256 over `canonical(value)`."""
    raw = hashlib.sha256(canonical(value).encode()).digest()
    return base64.urlsafe_b64encode(raw).decode()[:22]


def vocabularies(contract: int, version: str, groups: list[dict]) -> dict:
    """The `vocabularies` answer: the lists, the nestings and the groups."""
    return {"contract": contract, "version": version, "lists": lists(),
            "nesting": nesting(), "groups": groups}


def declarations(answer: dict) -> str:
    """The digest of a `vocabularies` answer, as `stamps` hands it back."""
    return digest(answer)
