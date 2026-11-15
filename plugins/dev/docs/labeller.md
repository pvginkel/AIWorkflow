# The labeller — the workflow's labels for the analysis dashboard

Pilot's analysis dashboard reads every Claude Code transcript on the fleet's home. Pilot's
collector reads their facts off Claude Code's format and knows nothing of this workflow. Every
label that interprets a transcript as the workflow's work is this plugin's, and so is every list
a label takes its value from: the slice a session served, the round it ran, what a call was
doing, which build a wait was on, what class a file is. `tools/labeller.py` is the command the
collector runs for them. It reads a batch of transcripts with the run records beside them and
hands back their labels, marked with the plugin's version, and it declares its own
vocabularies. Pilot's code names none of them.

The binding record is PilotAppSpecs' design record. The collection is `design/features.md` F152, the
file classes F158.5, and the collector's stub labeller F122.5. The entities are `design/database.md`
§2.5 to §2.11, with decision 79 (the data) and decision 81 (labelling what was appended). The
operator's rulings for this tool are `tools/cost-dashboard/asks/t14-incremental-labelling.md` (D1 to
D5) and `asks/t17-labeller.md` (D1 to D4), and its cards are AIWF-157, AIWF-189 to AIWF-195 and
AIWF-202. This page says how the labeller meets that record. It restates none of it beyond a cite.

Four rulings shape everything below:

- "Pilot app stays independent of the exact workflow implementation."
- "Every label and its vocabulary is the workflow labeller's."
- "A relabel overwrites every label it covers, and no older label is kept."
- "Rules over the data; no model call judges anything."

The prototype it replaces is `PilotAppSpecs/tools/cost-dashboard/collect.py`. Where the labeller
departs from it, § Where it departs from the prototype says so.

## Running it

**The command.** The collector reads the installed plugin from the home's
`plugins/installed_plugins.json`: the entry `dev@aiworkflow` and its `installPath`, rewritten from
the fleet's home to the collector's mount. It runs this command, which its own configuration names:

```
python3 -B <installPath>/tools/labeller.py <verb>
```

The script is stdlib-only, needs Python 3.11 or later for `tomllib`, and imports its sibling
modules from its own folder, as the other tools do. It writes nothing anywhere: no cache, no log
and no bytecode (`-B`). The pod mounts the home read-only, and all state between two calls is
carried by the collector (§ Settled, the boundary and the checkpoint; § The stamp, *The index*).
It reads only two places, both named in each request: the `projects` folder and the `plugins`
folder.

**One request in, one answer out.** Every verb reads one JSON document on stdin and writes its
answer to stdout. The answer is one JSON document, except `label`, which streams JSON Lines.
Every request carries the following keys:

```json
{"contract": 1,
 "home": {"projects": "/mnt/home/.claude/projects", "plugins": "/mnt/home/.claude/plugins"}}
```

- `home.plugins` is the folder whose `data/` holds the run records. The data folder inside it is
  the one `plugin_data_dir` names ([runner-state.md](runner-state.md) § The run records), from
  the plugin's installed key: the cache layout the script runs from, else the one key of the
  plugin's name in `installed_plugins.json`. `home.data` overrides it, for a test. Where neither
  names a folder, the request is refused `home`.
- **The contract** is an integer the labeller speaks. This page is contract 1, and every answer
  names it. It changes only when a request or an answer changes shape. A new rule within the same
  shapes is a new plugin version, which relabels everything (F152.6). A request whose contract the
  labeller does not speak is refused with `{"error": {"code": "contract", "detail", "speaks":
  [1]}}` and exit 2, and the collector then labels nothing.
- **The version** in every answer is the plugin's, from `.claude-plugin/plugin.json`. It is what
  Pilot stores as a Transcript's `labelled_under`.

| Verb | Reads | Answers |
|---|---|---|
| `info` | nothing: it takes any request, and checks neither its contract nor its home | `{"contract", "version", "verbs"}` |
| `vocabularies` | the run records' `groups/` | every declared list, the nestings and the groups (§ The vocabularies) |
| `stamps` | the run records, never a transcript | the stamp each transcript would get now, the declarations' and the file rules' stamps, the index (§ The stamp) |
| `label` | the transcripts it is handed, and the run records | their labels, whole or appended, one line per transcript (§ The label request and answer) |
| `classes` | the run records' `projects/` and run folders | the class of each file it is handed (§ File classes) |
| `check` | transcripts on a home, named by flags rather than a request | the replay check's report, for a person (§ The replay check) |

**Exit codes.** **0**: answered, which includes an answer that holds per-transcript errors. **2**:
the request was refused, with `{"error": {"code", "detail"}}` on stdout. The codes are `json` (the
request is not JSON), `request` (it is not an object, or a field the verb reads has the wrong
shape), `verb` (an unknown verb), `home` (no `home`, or no data folder it names) and `contract`.
**1**: the labeller crashed, with a traceback on stderr. On exit 1 the collector takes nothing
from that call, except the `label` lines that came before the crash (§ The label request and
answer). `check` exits by its own rule (§ The replay check).

**One bad transcript fails only itself.** In a `label` answer, a transcript that cannot be
labelled gets this line:

```json
{"session_id", "agent_id", "answer": "error", "error": {"code", "detail"}}
```

The codes are:
- `unreadable`: the file is missing or cannot be read.
- `calls_mismatch`: a whole labelling whose Calls differ from the ones the labeller reads in the
  file. `detail` names the first one that differs.
- `internal`: a rule raised an exception. `detail` is its last frame.

The batch goes on after an error. The collector publishes that transcript's facts with no labels,
as F152.6 has it for one that no labeller covers, and asks again at the next walk.

## Names both sides compute

The collector publishes facts and the labeller publishes labels of the same rows. So every row is
named by something both of them can compute from Claude Code's format or from what Pilot hands
over:

| Row | Named by |
|---|---|
| Transcript | `session_id`, and `agent_id` for a sub-agent, as Pilot's Transcript has them |
| Call | `id`, the assistant line's `message.id`, which is Pilot's Call `message_id`. The collector hands its Calls and the labeller labels exactly those (below) |
| Launch | `n`, its place among its Transcript's Launches in file order, from 1. The collector hands each Launch with its `started_at` |
| Tool Call | `tool_use_id` |
| Segment | `position`, from 1 |
| Event, Context Part | the Call they hang on, by `id`, with their own fields |
| Document | Pilot's id for it, as handed |
| Work Unit | `key` (§ Work Units) |
| CI Build | `job` and `number` |
| Test Suite, Test | the suite's `code`; a Test by its suite's code and its `name` |
| Adopted group | its `key` (§ Work Units, *The groups*) |

**The Calls are the collector's.** A Call in the file is every distinct `message.id` of an
assistant line, in the order of its first line, a `<synthetic>` model line and a line with no
`usage` included. The file's last line, with no newline yet, is read if it parses. A whole request
lists every Call with its `id`, `position` and `launch`, and an appended request lists those from
the boundary on. The labeller reads the file and matches each handed Call to its assistant lines
by `message.id`; Calls that differ are `calls_mismatch`. It labels every handed Call and no other.
A *counted* Call is one `turn_profile.replay` counts as a turn. A Call it does not count, such as
a `<synthetic>` one, takes the Segment of the Call before it (of the Call after it, where it is the
first) and no other label, so the Segments still cover every Call (assertion 554).

## What Pilot hands with a conversation

A *conversation* here is a main thread with its sub-agents. The collector groups each batch by
conversation (F152.4). With each conversation it hands what Pilot's inventory holds for it
(F152.2):

```json
{"session_id": "4eacca94-…",
 "sessions": [{"id": "…", "kind": "work", "created_at": "2026-11-15T18:47:02Z",
               "brief": "/dev:run-slice 001_now_playing", "repo": "SonosDisplay",
               "clarification": false}],
 "documents": [{"id": "…", "session": "…", "source_path": "/work/SonosDisplaySpecs/slices/001_now_playing/asks/1-run-question.md"}],
 "transcripts": [{"agent_id": null, …}, {"agent_id": "a1b2…", "agent_type": "Explore", …}]}
```

- **`sessions`** holds Pilot's Sessions on the conversation in `created_at` order, and is empty
  for a conversation Pilot does not know. For each Session it gives:
  - `kind`, Pilot's Session Kind code;
  - `brief`, the first 400 characters of its first Turn that no person wrote;
  - `repo`, the Work's `repo`, else its Project's;
  - `clarification`, true where the Work is a Clarification Run.
- **`documents`** holds the Documents those Sessions registered or wrote. `source_path` is set for
  a registered one and null for one of Pilot's own (database.md, Prose Item's `source_path`).
- **`agent_type`** comes with each sub-agent's transcript. It is the collector's fact,
  Transcript's `agent_type`, so the labeller never reads `agent-*.meta.json`.

**Once per request** (a header beside `home`): `"pilot": {"conversations": [...]}` lists the
`session_id` of every conversation any Pilot Session ran. Only the adoption rule reads it (§ Work
Units, *The groups*): "a slice any Pilot session ran is not adopted".

**Not read in contract 1: the steps a run published.** The record lists them among what Pilot
hands. The run records name every dispatch from its first seconds (`state.json`'s `in_flight`), so
the steps add nothing a label needs. The collector may leave them out.

## The stamp

A transcript's labels are a function of three things: its file, the labeller's version and its
stamp. The stamp covers all the labeller read for that transcript besides the file: the run
records, what Pilot handed with the transcript, and what it took from another transcript of the
conversation (F152.7; decision 81.3). A stamp that differs makes the collector relabel the
transcript whole. The collector asks for the stamps at every walk, every 30 s, so `stamps` must
answer for every transcript on the home without reading any of them.

**What a stamp covers is the facts the labelling took, never a file's bytes or time.** A running
slice's `state.json` is rewritten at every step. A stamp of that file would relabel every
transcript of the slice at every walk, and that is the cost the appended path exists to avoid.
So the stamp is a digest of the derived inputs the rules below read. A rewrite that changes none
of them changes no stamp. The inputs are:

- **Of the context:** the Sessions' `kind`, `brief`, `repo`, `clarification` and `created_at`,
  which places a Launch on its Session, and their order; the Documents' ids, Sessions and source
  paths; a sub-agent's `agent_type`; and whether a slice the transcript serves is run by Pilot (the
  `pilot` header, reduced to that one bit). A sub-agent's stamp covers the conversation's context
  as its main thread's does.
- **Of the run records:** the rows of every Work Unit the transcript's labels name (§ Work Units).
  That is the unit of each Launch and every unit above it through `part_of` and
  `occasioned_by`, with their measures. For the stage's anchor it is every unit of its stage
  with their Test Runs. Add the role its turns are classed under and the group its main thread is
  adopted by.
- **Of another transcript of the conversation:** nothing in contract 1. A sub-agent is labelled
  from its own file and its `agent_type` alone. The slot stays, so that a later rule which takes
  something from the main thread puts it in the stamp.

Because a transcript's tie to a slice is found from its session id in the run records, or from the
context, the inputs above can be computed without the file. There is one exception. Under the
adoption rules R2 to R4, an old interactive or headless session is tied to a slice by what its own
first prompt names (§ Work Units, *The groups*). Those slice names come from the file, so the stamp
carries them. A stamp is the text

```
1:<digest>[:<named>]
```

- `<digest>` is 22 characters of url-safe base64 of the sha256 over the canonical JSON of the
  inputs.
- `<named>` lists, comma-separated, the slices the transcript's own content named, as named. The
  name that tied it carries its unit after `@`: `PilotAppSpecs/044@run`, `…@close-out`,
  `…@run.P2` for an R3 session's phase. A name tried before it, which tied nothing, stays bare.
  The digest covers every unit of each named slice, so a change anywhere in that slice changes
  the stamp.

`stamps` recomputes a transcript's digest from the `<named>` part of the stamp Pilot holds for it,
so it never needs the file. Pilot stores the stamp as opaque text and compares it for equality
alone (database.md, Transcript's `records_stamp`).

**The request and the answer.**

```json
{"contract": 1, "home": {…}, "pilot": {…}, "index": "<the last answer's index, or null>",
 "conversations": [{"session_id", "sessions", "documents",
                    "transcripts": [{"agent_id": null, "held": "1:…"},
                                    {"agent_id": "…", "agent_type": "…", "held": null}]}]}
```
```json
{"contract": 1, "version": "0.10.81",
 "declarations": "<digest>", "file_rules": "<digest>", "index": "<blob>",
 "stamps": [{"session_id", "agent_id", "stamp"}]}
```

- `held` is the stamp Pilot holds, or null.
- The stamps come back in request order. A transcript whose stamp cannot be computed gets
  `"stamp": null`, as one that no labelling covers, and the others are answered.
- `declarations` is the digest of what `vocabularies` would answer now. The collector loads the
  vocabularies and the groups again whenever it changes, and before it publishes a label of a new
  version.
- `file_rules` is § File classes'.

**The index.** To find which slice names a session id, the labeller needs every run record's
history, and reading and parsing all of them is most of a cold call's cost, which grows with every
slice. So `stamps` and `label` hand back `index`, an opaque blob of what they parsed, keyed by
each records file's size, `mtime_ns` and inode. The collector keeps it in memory and hands it back
at the next call. The labeller then stats the data folder and parses again only the files that
changed.

- A missing, stale or foreign index is rebuilt. It is never an error and never changes an answer,
  only the cost.
- It is marked with the version and is at most 16 MiB. Past that the labeller hands back none
  (`"index": null`).

**The cost.** These are targets, timed on the home before a release as the collector runs the
command, the process's start and the JSON included, not promises:
- `stamps` over 20,000 transcripts with a warm index: under half a second;
- `classes` over 100,000 files: under a second.

Both are ordinary work in one process: hashing the canonical inputs, with the rows of each set of
units digested once per call.

## The label request and answer

```json
{"contract": 1, "home": {…}, "pilot": {…}, "index": "<blob or null>",
 "conversations": [{"session_id", "sessions", "documents", "transcripts": [ … ]}]}
```

A transcript to label whole:

```json
{"agent_id": null, "path": "-work-SonosDisplay/4eacca94-….jsonl", "mode": "whole",
 "launches": [{"n": 1, "started_at": "2026-11-15T18:47:09.112Z"}],
 "calls": [{"id": "msg_01…", "position": 1, "launch": 1}, …]}
```

A transcript to label from its boundary on (F152.15; AIWF-157, "the Call and the byte of the file
the part starts at, the facts of the Calls from there on, and the checkpoint"):

```json
{"agent_id": null, "path": "…", "mode": "appended",
 "from": {"call": "msg_01…", "byte": 1048576}, "checkpoint": "<as handed back last time>",
 "launches": [ the boundary Call's Launch and every later one ],
 "calls": [ the boundary Call and every later one ]}
```

- `path` is relative to `home.projects`.
- A sub-agent gives no `launches`, and its Calls no `launch` (assertion 543).
- `from` and `checkpoint` are exactly what the last answer handed back. The collector hands them
  back only where Pilot's inventory names exactly the size, time, versions and stamp they were
  built on (F152.1). Whether the file still continues what Pilot holds is the collector's check
  (F152.17), made before it asks.

**The answer is JSON Lines.** The first line is `{"contract", "version"}`. Then comes one line per
transcript, in request order, main threads before their sub-agents. The last line is `{"done": true,
"count": n, "index": "<blob>"}`, where `n` counts every transcript line, error lines among them.
Lines are written and flushed as each transcript is done. If the
collector's time limit cuts a batch short, the lines before the cut stand, and a missing `done` line
says the batch was cut.

```json
{"session_id", "agent_id", "answer": "labels", "stamp": "1:…",
 "boundary": {"call": "msg_01…", "byte": 2097152}, "checkpoint": "…",
 "labels": {"transcript", "launches", "calls", "segments", "tool_calls", "events",
            "context_parts", "test_runs", "ci_waits", "documents"},
 "units": [ … ], "test_suites": [ … ], "ci_builds": [ … ]}
```

**The fields of `labels`**, each a list of rows named as in § Names both sides compute. A whole
answer gives every row. An appended answer gives those from the boundary on, and a few always:

| Field | Row | Appended answer |
|---|---|---|
| `transcript` | `{"adopted_group": key or null}`, on a main thread only | always |
| `launches` | `{"n", "work_unit": key or null}` | the boundary Call's Launch and later |
| `calls` | `{"id", "segment", "call_class", "avoidable_kind", "batchable_condition", "wait_cause"}`, null where there is none | every handed Call |
| `segments` | `{"position", "kind"}` | from the Segment the boundary Call falls in, as now labelled; Pilot replaces every Segment from that position on |
| `tool_calls` | `{"tool_use_id", "command_class", "effect_kind", "effect_subject", "rules": [codes]}`, only for a Tool Call with at least one | those of the handed Calls |
| `events` | `{"call", "kind", "at", "detail"}`, the labeller's own kinds | those of the handed Calls |
| `context_parts` | `{"call", "kind": "digest_section", "name", "characters"}` | those of the handed Calls |
| `test_runs` | § Test Runs and CI Builds: a Tool Call's with its `tool_use_id`, a unit's with its `work_unit` | those of the handed Calls' Tool Calls; on the anchor, its stage's too |
| `ci_waits` | `{"tool_use_id", "job", "number"}` | those of the handed Calls' Tool Calls |
| `documents` | `{"id", "ask_category"}`, on a main thread only | always |

- **`units`** holds the whole row of every Work Unit the labels name, and of every unit above
  them. On the stage's anchor it holds every unit of the stage. They come in an order where a
  unit's `part_of` and `occasioned_by` stand before it. Pilot writes a unit by its `key`. A unit's
  row is a function of the run records alone, never of the transcript carrying it, so two
  transcripts that name a unit under one stamp carry the same row.
- **`test_suites`** holds each suite a Test Run names, as `{"code", "name"}`.
- **`ci_builds`** holds each build a CI Wait names, as § Test Runs and CI Builds gives it.

Pilot writes these three by their keys. It never deletes one at a relabel, since they are not a
Transcript's own rows (database.md §7.1).

**The answer `whole`.** Where an appended request cannot go on from its checkpoint, the line is
`{"session_id", "agent_id", "answer": "whole", "why"}`. The collector then has the same transcript
labelled whole in the same walk (AIWF-157). `why` is one of:
- `checkpoint`: the checkpoint is from another version or contract, unreadable, or not this
  transcript's;
- `stamp`: the stamp now differs from the one the checkpoint was built under;
- `boundary`: the line at `from.byte` is not the boundary Call's first line;
- `behind`: an appended line reaches behind the boundary: a tool result for a Call whose result
  was owed at the boundary (§ Settled, the boundary and the checkpoint);
- `calls`: the handed Calls do not continue the checkpoint's.

## Settled, the boundary and the checkpoint

**When a Call is settled** (F152.15). Its labels stop changing once the next Call's first line is
in the file, as a rule. What a rule below reads about Call *i* comes before that line:

- its tool results;
- the user line that says whether a task notification came next (`turn_profile`'s `notified`);
- the lines before it that woke the transcript;
- the two turns before it that `retry` and `fumble` read;
- the lagged context that `batchable` reads.

The last Call is always open. Its labels are given as if it were the last: `turn_profile` classes
a last turn with no tool as `record`. If more is appended, the open Call is labelled again. A
whole labelling of the file as it stood gives the same, so a full replay agrees.

A line can still reach back past the next Call's first line: a result that arrives after it, or
an assistant line that adds a call to an earlier message. The Call it touches is settled only
once that line is read.

**The one stretch that stays open longer** is a background wait on a build. A `track_build.py` run
with `run_in_background` gets its result at once, and its summary reaches the transcript later,
in a later Tool Call's result. The CI Wait is a label of the waiting Tool Call, so that Call stays
open until one of three things happens:

- its summary is matched (§ Test Runs and CI Builds);
- its Launch ends, which means a later Launch began (a sub-agent has no Launch, so only the other
  two close its stretch);
- 20 counted Calls have passed since the task notification that names its `tool_use_id`. A
  summary in the 20th Call's result still matches.

After the second or the third it makes no CI Build: "ran in the background unread" (database.md,
CI Wait). The bound keeps a transcript that never reads its waiter's output from holding its
boundary open for the rest of its life.

**The boundary** is the latest counted Call before whose first line every earlier Call is
settled. What holds it back is a Call a later part could still touch: an open CI wait, a result
still to come after that line, a call added to an earlier message after it, or a wait matched
after a later wait on its job opened. Each holds the boundary back to its own Call; with none,
the boundary is the last counted Call. `boundary.call` is that Call's id. `boundary.byte` is the
offset of its first assistant line. The labeller's state is taken just before that line, so
labelling again from there recomputes the boundary Call itself: its wake, its class and its
Segment. A Call `replay` does not count is never a boundary. The boundary moves back only by a
whole labelling. A transcript with no counted Call has a null boundary and no checkpoint, and the
collector labels it whole when it grows.

**The checkpoint** is the labeller's state at the boundary, opaque to the collector and to Pilot.
It is the text `1:<version>:<base64 of zlib-compressed JSON>`. That JSON holds the following:

- the transcript's ids and the contract;
- the stamp it was built under;
- the boundary;
- the count of counted Calls before it;
- `turn_profile`'s classifier state at the boundary: what the last two turns left behind for the
  rules that look back, the lagged path sets, whether an edit has been seen, and the place in a
  run of reads;
- the Segment the Call before the boundary fell in, and its kind;
- what woke the transcript since the Call before: a person's prompt, a task notification, the
  last tool whose result arrived, an opening prompt's digest sections;
- that Call's tools and its Launch;
- the running Launch's background tasks not yet notified as ended, with the files they write
  (`no_tail_on_background_log`);
- the tool-use ids of Calls whose results are still owed. A result for one of them in a later
  part is `behind`; a result for any other id changes no label, as in a whole replay.

No open stretch is in it: a CI wait still open holds the boundary at its own Call, so the part
from the boundary on reads that wait again. A Launch's tie is not in it either: the stamp names
the run records it was taken from.

It is at most 256 KiB. One that would be larger is not handed back (`"checkpoint": null`), and the
next labelling is whole.

**One engine.** A whole labelling is the appended path run from byte 0 with an empty state. Its
specification is a full replay (F152.16), and having one engine makes the parts and the whole
agree by construction. § The replay check holds it there.

## The vocabularies

`vocabularies` answers every list a label takes its values from, the nestings of the Work Unit
Kinds, and the groups:

```json
{"contract": 1, "version": "…",
 "lists": {"work_unit_kind": [{"code": "slice", "name": "Slice", "description": "…", "position": 1}, …], …},
 "nesting": [{"inner": "stage", "outer": "slice"}, …],
 "groups": [{"key", "spec_repo", "name", "summary", "slices": [...]}]}
```

Every value has a `code`, a `name`, a one-line `description` and a `position` that is unique
within its list (assertion 585). The extra facts sit beside them. The lists are named after the
record's reference entities (database.md §2.11, "the labeller's"). `position` is the order of the
rows below, and each `description` is the line given here. Declared lists:

**`work_unit_kind`:**

| Code | Name | Description |
|---|---|---|
| `slice` | Slice | A slice: everything done for one folder of a spec repo. |
| `stage` | Stage | One stage of a slice: its planning, its run, or for an old slice its triage or close-out. |
| `phase` | Phase | One phase of a slice's plan, from its first round to its merge. |
| `dispatch` | Dispatch | One dispatch of one role in one round, as the driver recorded it. |
| `sweep` | Sweep | A loop-tail gate sweep the driver ran. |
| `gate` | Gate | A gate the driver ran: a phase's gate, or the doc, wrap-up or fixes gate. |

A driver's gate is a kind of its own (O2, settled).

**`nesting`** gives each allowed pairing as inner ⊂ outer:
- stage ⊂ slice;
- phase ⊂ stage;
- dispatch ⊂ phase;
- dispatch ⊂ stage;
- sweep ⊂ stage;
- gate ⊂ phase;
- gate ⊂ stage.

**`unit_outcome`:**

| Code | Name | Description |
|---|---|---|
| `done` | Done | The work ended as it should: a writer's round done, a phase merged, a stage or slice finished. |
| `signoff` | Signed off | A review that found nothing blocking. |
| `issues` | Issues | A review that found something blocking. |
| `red` | Red | A gate or sweep that failed. |
| `green` | Green | A gate or sweep that passed. |
| `question` | Question | A writer that stopped on a question only the operator can answer. |

The history's other words are open (O1).

**`rework_kind`:**

| Code | Name | Description |
|---|---|---|
| `rework` | Rework | Work done again: a second round, an appended phase, a consult other than the completion consult. |
| `consult` | Completion consult | The completion consult, priced apart from rework. |

**`unit_measure`** (extra fact: `unit`):

| Code | Name | Unit | Description |
|---|---|---|---|
| `planned_phases` | Planned phases | phases | The phases the plan held when it was done, less the ones the run appended. |
| `acceptance_criteria` | Acceptance criteria | criteria | The items of the slice's `verification.json`. |
| `review_findings` | Review findings | findings | The findings a review round reported. |
| `close_out_entries` | Close-out entries | entries | The entries of the slice's close-out report. |
| `close_out_fixed` | Close-out entries fixed | entries | Entries a change landed for. |
| `close_out_carded` | Close-out entries carded | entries | Entries handed on as a card or to another slice. |
| `close_out_closed` | Close-out entries closed | entries | Entries closed with no change. |

**`segment_kind`:**

| Code | Name | Description |
|---|---|---|
| `start` | Reading in | Reading before the first change. |
| `work` | Work | The work itself. |
| `gate` | Gate | Running a gate: tests, lint, build. |
| `records` | Records | The done-record, the verdict and the commit. |
| `wait` | Waiting | Waiting on a command, a build or a background task. |

**`wait_cause`:**

| Code | Name | Description |
|---|---|---|
| `command` | A command | Its own foreground command ran. |
| `sub_agent` | A sub-agent | A sub-agent it dispatched ran. |
| `background_task` | A background task | It waited for a background task to end. |
| `person` | A person | It waited for a person's message. |
| `hold` | A hold | Pilot held it from running. |
| `driver` | Its driver | The loop that dispatched it started it again. |
| `startup` | Startup | Its process was starting. |

**`call_class`** is the plugin profile's classes, `turn_profile.TURN_CLASSES`, in its order:

| Code | Name | Description |
|---|---|---|
| `dispatch` | Dispatch | Started another session or a sub-agent. |
| `edit` | Edit | Changed a file of the work. |
| `gate` | Gate | Ran a test suite, a lint or a build. |
| `commit` | Commit | Changed git's state: a commit, a merge, a push. |
| `record` | Record | Wrote the run's own record, or handed back with no tool at its end. |
| `retry` | Retry | Ran again what failed in the two calls before. |
| `fumble` | Fumble | A tool call that failed. |
| `wait` | Wait | Waited on a command, a build or a background task. |
| `git-inspect` | Git inspect | Read git's state alone. |
| `orient-read` | Orienting read | Read before the session's first change. |
| `work-read` | Working read | Read after the first change, or a reviewer's reading. |
| `think` | Think | No tool, with nothing running. |
| `other` | Other | Anything else. |

**`avoidable_kind`:**

| Code | Name | Description |
|---|---|---|
| `retry` | Retry | Ran again what had just failed. |
| `fumble` | Fumble | A call that failed. |
| `batchable` | Batchable | A read that could have gone with the reads before it. |

**`batchable_condition`** is the list that t17 D4 ruled, held in `turn_profile.BATCHABLE_WHYS`:
its codes, names and descriptions, in its order. The record has no place for this label yet. A P
card proposes one, and slice 052 stores it once the record does.

**`command_class`:**

| Code | Name | Description |
|---|---|---|
| `test_suite` | Test suite | Runs a test suite. |
| `gate` | Gate | Runs a gate of the workflow's, or a lint or a build. |
| `ci_wait` | CI wait | Waits on a Jenkins build and its deploy. |
| `chunked_wait` | Chunked wait | A loop's or a long command's wait, in chunks under the cache's lifetime. |
| `sleep_poll` | Sleep-poll | Sleeps, and checks again. |
| `git` | Git | A git command. |

The rows are in the record's order. The rules are tried in the order § The labels, by entity
gives.

**`build_result`** is Jenkins's words as the summary prints them:

| Code | Description |
|---|---|
| `SUCCESS` | The build passed. |
| `FAILURE` | The build failed. |
| `ABORTED` | The build was stopped. |
| `UNSTABLE` | The build ran with test failures. |
| `NOT_BUILT` | The build did not run. |

Each one's name is its code.

**`file_class`** (extra fact: `counted`):

| Code | Name | Counted | Description |
|---|---|---|---|
| `code` | Code | yes | What builds and runs the product, its configuration included. |
| `test` | Tests | yes | Tests and their fixtures. |
| `docs` | Docs | yes | A product repository's documentation. |
| `spec` | Spec | yes | What a spec repo holds that was written. |
| `generated` | Generated | no | What a tool writes. |
| `record` | Record | no | What a run writes about itself in its slice's folder. |

**`tool_effect_kind`:**

| Code | Name | Description |
|---|---|---|
| `card_created` | Card created | Created a card on the tracker. |
| `card_updated` | Card updated | Changed or commented on a card. |
| `fieldnote_posted` | Fieldnote posted | Posted a fieldnote. |
| `document_registered` | Document registered | Registered a document with Pilot. |
| `push` | Push | Pushed to a remote. |

**`rule`** (extra fact: `home`, the file that states it):

| Code | Name | Home | Description |
|---|---|---|---|
| `no_sleep_poll` | No sleep-poll | `/etc/claude-code/CLAUDE.md` | Work that reports back is waited on by ending the turn, never by sleeping and checking. |
| `no_git_add_all` | No `git add -A` | `/etc/claude-code/CLAUDE.md` | Stage nothing until the commit, and commit by path. |
| `no_tail_on_background_log` | No tail on a background log | `/etc/claude-code/CLAUDE.md` | Never tail the log of a backgrounded command to see how far it got. |

**`ask_category`:**

| Code | Name | Description |
|---|---|---|
| `requirements` | Requirements | The plan-preparer's requirements asks. |
| `plan_question` | Plan question | A question the planning put. |
| `plan_review` | Plan review | The plan review's findings put to the operator. |
| `run_question` | Run question | A question the run put. |
| `close_out` | Close-out | The slice's close-out report. |
| `pilots_own` | Pilot's own | A document Pilot itself put. |

**`event_kind`**, the labeller's own (extra fact: `is_error`):

| Code | Name | Description |
|---|---|---|
| `gate_red` | Gate red | A gate or a test suite a session ran came back red. |

Its `is_error` is open (O8): until it is ruled, null.

**`context_part_kind`**, the labeller's own:

| Code | Name | Description |
|---|---|---|
| `digest_section` | Digest section | One section of the orientation digest the driver handed a dispatch. |

## The labels, by entity

Each rule below reads the transcript's own lines and what § What Pilot hands with a conversation
gives. § Work Units gives the session's *tie*: its slice, stage, round and role, from the run
records.

**Transcript**, main threads only. `adopted_group` is the key of the group whose adopted slice the
transcript served (§ Work Units, *The groups*), and none otherwise.

**Launch.** `work_unit` is the lowest Work Unit the Launch carried out (assertion 553), by its tie
(§ Work Units). It is none for a Launch that served no unit.

**Call.**

- **`call_class`** is `turn_profile.classify_turns`' class for the Call's turn. The turn is one
  billed assistant message, by `message.id`, as `replay` reads it. The flags come from the
  transcript's role (`slice_cost.turn_flags`):
  - a loop dispatch's main thread takes its history row's role;
  - a stage's own session takes `orchestrator:<stage>`, whether Pilot ran it or not;
  - a sub-agent takes `subagent:<agent_type>`;
  - anything else takes none, an R3 session included.
- **`avoidable_kind`** is `retry` or `fumble` where the class is that, else `batchable` where
  `batchable_strict` holds. The prototype's `avoid_of` reads them the same way.
- **`batchable_condition`** is the turn's `batchable_why` code, on a read-class turn only
  (`orient-read`, `work-read`, `git-inspect`).
- **`segment`** is the position of the Segment the Call falls in.
- **`wait_cause`** is what woke the transcript between the Call before and this one. The first of
  these rules that holds decides it. In rules 1 to 4, a first Call is the first counted one:
  1. The first Call of the transcript: `startup`.
  2. The first Call of a later Launch, in a transcript the run records name as a dispatch: `driver`.
  3. The first Call of a later Launch, in a transcript neither Pilot nor the run records know:
     `person`.
  4. The first Call of a later Launch of a Pilot conversation: open (O3). Until it is ruled, none
     (`labeller_engine.O3_LATER_LAUNCH_OF_PILOT`).
  5. A person's prompt came in between: a user line that is no tool result, no task notification
     and not meta, as `turn_profile`'s `_user_text_kind` reads it: `person`.
  6. A task notification came in between, or the Call before waited on a background task
     (`TaskOutput`, `BashOutput`, `Monitor`): `background_task`.
  7. The Call before ran tools: the one whose result arrived last decides, or with no result yet,
     the Call before's last tool. An `Agent` (or `Task`) call gives `sub_agent`; any other gives
     `command`.
  8. Otherwise none.

**Segment.** Each Call has a kind, `turn_profile`'s class read through this table, the one the
prototype has (`analysis.py`'s `CLS_KIND`):

| Class | Kind |
|---|---|
| `orient-read` | `start` |
| `gate` | `gate` |
| `commit`, `record` | `records` |
| `wait` | `wait` |
| anything else | `work` |

A Segment is a maximal run of consecutive Calls of one kind, in `position` order. That gives one
partition of the Transcript's Calls, and two stretches of one kind are two Segments (assertion
554; decision 79.24). A settled Call's class is final, so its Segment keeps its position and its
kind (§4.33).

**Tool Call.** The rules read a `Bash` command through `turn_profile`'s shell reading
(`bash_segments`, `_unwrap`), so `cexec`, `timeout` and `cd … &&` wrappers do not hide the
program.

- **`command_class`** is the first of these that holds:
  1. `ci_wait`: it runs `track_build.py`.
  2. `chunked_wait`: it runs `run_loop.py wait`, `plan_loop.py wait` or `long_run.py wait`.
  3. `gate`: it runs `run_loop.py gate` or `spec_check.py`.
  4. `test_suite`: it runs `kc project test`, `pytest`, `go test`, `playwright test`,
     `vitest` (bare or through `npx`, `pnpm` or `yarn`), `node --test`, `npm test`, `pnpm test`,
     `yarn test` or `uv run --with pytest`. `npm test`, `pnpm test` and `yarn test` cover
     `run test`, a `test:<script>` and the folder options before the script.
  5. `gate`: it runs `kc project lint|build`, `ruff`, `mypy`, `tsc`, `golangci-lint` or
     `ansible-lint`.
  6. `sleep_poll`: it has a `sleep <n>` segment.
  7. `git`: its program is `git`.

  A matching program name inside quoted text or a heredoc does not count.
- **`effect_kind` and `effect_subject`**, from a successful call alone:

  | Tool Call | Effect kind | Subject |
  |---|---|---|
  | `mcp__youtrack__create_issue` | `card_created` | the new card's id, from the result |
  | `mcp__youtrack__update_issue`, `mcp__youtrack__add_comment` | `card_updated` | the card's id, from the input |
  | `mcp__fieldnotes__post` | `fieldnote_posted` | the fieldnote's id, from the result |
  | `mcp__pilot__register_document` | `document_registered` | the path it was given |
  | a `git push` that exited 0 | `push` | none |

  Any `mcp__<server>__<tool>` whose tool is one of these counts, whatever the server's name. A
  `post` that answers `"id": null`, a fieldnote the store already held, has no effect. A push has
  exited 0 where the call succeeded and its output shows no rejection.
- **`rules`** lists the codes of the Rules the call breached:
  - `no_sleep_poll`: a poll loop, a `while`, `until` or `for` loop that sleeps and runs a check
    in its body, whatever the command's class. A single sleep that lets something settle, as in
    `sleep 5 && curl …`, breaches nothing.
  - `no_git_add_all`: `git add -A`, `git add --all`, `git add .`, or `git commit` with `-a`
    (`-am`). Whether this counts only in a shared tree is open (O9); until it is ruled, it counts
    in any tree.
  - `no_tail_on_background_log`: a `tail` of a file that a background task of the same Launch is
    still writing. That means the output file its notification will name, or the target of a
    `>` or `tee` in a `run_in_background` command, where that task has not yet been notified as
    ended.

**Event**, the labeller's own. `gate_red` marks a Tool Call whose command class is `gate` or
`test_suite` and whose result failed: a non-zero exit, or `is_error`. Its `call` is the Call that
asked for the Tool Call. Its `at` is the result line's time. Its `detail` is the `kc` project and
verb (`frontend test`), else the program.

**Context Part**, the labeller's own. On the first Call of a Launch of a dispatch, the opening
prompt's orientation digest gives one `digest_section` per `## ` section of the block that opens
`# Orientation digest —`. These are `run_loop.build_phase_digest` and `build_slice_digest`.
`name` is the heading up to its first ` (`. `characters` is the section's length with its heading.

**Document.** `ask_category` comes from the source path and from which Session put the document:

| Document | Ask category |
|---|---|
| no `source_path` (Pilot's own), or put by a `chat` or `job` Session | `pilots_own` |
| `<slice>/close-out.md` | `close_out` |
| `<slice>/asks/<n>-requirements.md` | `requirements` |
| `<slice>/asks/<n>-plan-review.md` | `plan_review` |
| any other `<slice>/asks/<n>-<slug>.md`, put by a plan stage's Session | `plan_question` |
| any other `<slice>/asks/<n>-<slug>.md`, put by a run stage's Session | `run_question` |
| anything else | none |

Here `<slice>` is a slice folder, by § File classes' pattern alone, in whatever repository. The
stage is the putting Session's tie. The slugs are the ones the writers use: the plan-preparer's
`requirements`, the plan loop's `plan-review` and `plan-questions`, and the run loop's
`QUESTION_DOCS`. The record's samples put `asks/4-run-stopped-on-postgres-memory.md`, which a
run-slice session wrote, under `run_question` (`tools/cost-dashboard/logical-model.md` §5).

## Work Units

**How a session is tied to its unit.** The run records are the authority. The index maps every
`session` of every history row, every `in_flight.session` and every `orchestrator.session` of
`runs/*/*/state.json` and `plan_state.json` to its slice, stage and row. Each main thread's
Launches are tied in this order:

1. **A dispatch.** Its session id is on one or more history rows, or is the `in_flight` of the
   slice's run. The Launch is tied to the dispatch whose row's `[started_at, ts]` holds the
   Launch's `started_at`, else to the first row ending after it. `started_at` is the row's, else
   `ts − duration_s` for a row from before 0.10.80. A Launch no ended row holds is the running
   round, named from `in_flight`; with no `in_flight`, a Launch after every row ended has no
   unit.
2. **A stage's own session.** Its session id is a state file's `orchestrator.session`. For a
   Pilot work item, that is Pilot's conversation id. Every Launch is the stage's, except one whose
   Pilot Session is a clarification, which is the slice's: the prototype gave a clarification its
   slice and no stage. A Launch's Pilot Session is the latest one created at or before its
   `started_at` plus 5 s, from the context. A session that orchestrated two stages, a plan and a
   run on one conversation, places each Launch the same way by the stages' `created_at`: the
   latest stage created by then, else the first.
3. **A Pilot stage before its loop.** The conversation's first Session has a brief that
   `^\s*/dev:(plan|run)-slice\s+(\S+)` matches, and no state file names it yet, as in a plan-slice
   stage while its plan-preparer runs. This gives no unit until the loop's state file names the
   conversation. A slice's key needs its spec repo, which only the run records give. When they
   arrive the stamp changes, and the transcript is labelled again whole.
4. **An old session** under the adoption rules R2 to R4 (*The groups*, below): the stage's unit, or
   for R3 its phase's.
5. Otherwise none. That includes every chat, job, conversation and dashboard Session, and every
   person's session no rule ties.

A sub-agent carries out no Launch, so its Calls reach their unit through their main thread's
Launch (assertion 543). A continuation Session on the same conversation is the same stage's,
since its conversation is the orchestrator's.

**Keys.** A key is the same at every relabel (database.md, Work Unit):

| Kind | Key | Example |
|---|---|---|
| slice | `<spec-repo>/<NNN_slug>`, the run records' folder names | `PilotAppSpecs/044_web_push` |
| stage | `<slice>\|<stage>`, the stage being `plan` or `run`, or for an old slice `triage` or `close-out` | `PilotAppSpecs/044_web_push\|run` |
| phase | `<slice>\|run\|P<id>` | `…\|run\|P1` |
| dispatch in a phase | `<phase>\|<role>\|<round>` | `…\|run\|P1\|code-writer\|1` |
| dispatch in a stage | `<stage>\|<role>\|<round>` | `…\|plan\|plan-reviewer\|2`, `…\|run\|test-agent\|1` |
| sweep | `<slice>\|run\|sweep\|<n>`, `n` the sweep's place among its stage's `sweep` rows, which is `sweeps/r<n>.json`'s `run` | `…\|run\|sweep\|1` |
| a phase's gate | `<phase>\|gate\|<round>` | `…\|run\|P1\|gate\|2` |
| a stage's gate | `<stage>\|<role>\|<round>`, the role being `doc-gate`, `wrap-up-gate`, `fixes-gate` or `fixes-doc-gate` | `…\|run\|doc-gate\|1` |

- `<role>` and `<round>` are the history row's own. The triple (phase, role, round) repeats in the
  history, as with a question and the round after its ruling, a reattached session, or old rows
  with no phase. So the *n*-th row of one such triple, in history order, takes `.<n>` after its
  round from the second on, as in `…|code-writer|1.2` or `…|gate|1.2`. History is append-only,
  so a row's key never changes.
- A row with no round takes its place among its role's rows in that phase or stage.
- A history row of the role `orchestrator` is no dispatch.
- A state file of the older task runner, with a `tasks` key, is read the same way: its `task` and
  `tasks` stand for the phases, and its run stage is done when its top-level `phase` is `done`.

**The attributes**, each read from the run records alone:

- **`title`:**
  - a slice: `slice.json`'s `title`, else its folder;
  - a stage: `Plan`, `Run`, `Triage` or `Close out`;
  - a phase: the label of its `P<id>.code` step in `progress`, else `P<id>`;
  - a dispatch: `<role> <round>`;
  - a sweep: `Gate sweep <n>`;
  - a gate: `Gate <round>`, `Doc gate <round>`, `Wrap-up gate <round>`, `Fixes gate <round>` or
    `Fixes doc gate <round>`.
- **`variant`:**
  - a stage: its stage;
  - a dispatch: the row's `kind` (`first`, `gate-fix`, `review-fix`, `ruling`, `fixes`), or a
    consult's `site`, where the row has one;
  - a gate: its row's role.
- **`role`:** a dispatch's, from its row. A gate has none.
- **`round`:** a dispatch's or a gate's, from its row; a sweep's `n`.
- **`card`:** a slice's, `slice.json`'s `card`, as given (AIWF-157).
- **`started_at` and `ended_at`:**
  - a dispatch, a gate or a sweep: its row's start and `ts`, or `in_flight.started_at` and none
    while it runs;
  - a phase: its first dispatch's start, and its last row's `ts` once its `status` is `merged`;
  - a stage: its state file's `created_at`, and its end once it is done. The plan stage is done
    when `plan_state.json`'s `phase` is `done`. The run stage is done when `state.json`'s
    `run_phase` is `done`. The end is `exit.ts` of a code-0 exit, else the last row's `ts`;
  - a slice: its earliest stage's start, and its run stage's end.
- **`outcome`:**
  - a dispatch, a gate or a sweep: its row's `outcome`, through the table below;
  - a phase, a stage or a slice: `done` once it is done, as above.

  | Role | History outcome | Unit Outcome |
  |---|---|---|
  | code-writer, plan-writer, doc-writer, wrap-up | `done` | `done` |
  | code-writer | `question` | `question` |
  | code-reviewer | `signoff` | `signoff` |
  | code-reviewer, plan-reviewer | `issues` | `issues` |
  | gate, sweep, doc-gate, wrap-up-gate, fixes-gate, fixes-doc-gate | `green` / `red` | `green` / `red` |
  | every other pair | | open (O1). Until it is ruled, none (`labeller_records.OTHER_OUTCOMES`, empty) |

- **`rework_kind`**, on dispatches, from `slice_cost.derive`'s rule:
  - The run's completion consults take `consult`. These are the consult rows whose `site` is
    `completion`, and on a row with no `site`, the first consult row of the run with no phase.
  - Every other consult, every dispatch of an appended phase, and every dispatch of round 2 or
    later that is not the continuation of a `question` or `blocked` row of its role and phase take
    `rework`.
  - The plan stage's dispatches take none.
- **`occasioned_by`**, on a dispatch, points at the unit whose outcome made it necessary:
  - a code-writer round of kind `review-fix`, or on a row with no `kind` one that follows an
    `issues` review in its phase: that review;
  - kind `ruling`, or a writer's row that follows its own `question` row, whatever its kind: that
    question's dispatch;
  - a code-writer round of kind `gate-fix`, or on a row with no `kind` one that follows a red gate
    or a test-fixer in its phase: the red gate before it;
  - a test-fixer in a phase: the red gate before it; one with no phase, on a sweep flake: the
    sweep before it;
  - a consult with a phase: the review before it;
  - a plan-writer round after the first: the plan-reviewer round before it.
- **Measures** (`unit_measure`):
  - `planned_phases` and `acceptance_criteria` sit on the slice, from `slice.json`'s `plan`.
  - `review_findings` sits on each code-reviewer and plan-reviewer dispatch. It counts the row's
    `findings`, else `slice.json`'s `code_review_findings[phase][round]` or
    `plan_review_findings[round]`, which the seed writes for rows that have none
    ([runner-state.md](runner-state.md) § The run records).
  - The four close-out figures sit on the run stage, from `slice.json`'s `close_out` (t17 D3: "on
    the slice's run").
  - A measure is left out where its fact is.

**The stage's anchor.** The units no Launch carries out are the sweeps and the gates, with the
driver's Test Runs. The *anchor* carries them, together with every other unit of its stage. The
anchor is the stage's `orchestrator.session` transcript, else, for a stage run by hand with no
orchestrator, the transcript of its first history row that names a session. The anchor's stamp
covers its whole stage, so it is labelled again whole when any unit of the stage changes. A run
stage's orchestrator is a small transcript of waits, so that costs tens of milliseconds.

**The groups.** `groups/<SpecRepo>.toml`, the seed's copy of the prototype's `adopted/*.toml`,
holds the header `spec_repo`, `repo` and `environment`, then `[[project]]` tables with `name`,
`summary` and `slices`. `vocabularies` declares each as `{"key", "spec_repo", "name",
"summary", "slices"}`, where `slices` are the keys of its adopted slices. A project with no adopted
slice is not declared, and an adopted slice no project lists gets a group of its own, so the
declared groups follow the `pilot` header.

- **The key** is `<SpecRepo>/<the lowest slice folder it lists>`. It survives a rename and slices
  added later. A group of its own is keyed `<SpecRepo>/<folder>` and named after its
  `slice.json` title, as the toml's own comment has it. If that slice later joins
  a group whose lowest slice it is, the project keeps its row and takes the group's name.
- **An adopted slice** is a slice of a spec repo that has a groups file, whose state files have no
  `tasks` key, and none of whose recorded sessions (orchestrators, history rows, `in_flight`) is
  in the `pilot` header's conversations. That last test is the record's "a slice any Pilot
  session ran is not adopted".
- **Adoption** is the prototype's `adopted_db`. A main thread goes to the first rule that takes it,
  in the order R1, R2, R4, R3:
  - **R1:** its session is an adopted slice's orchestrator or a history row's.
  - **R2:** an interactive session with no Pilot Session whose first person prompt is
    `/dev:plan-slice` or `/dev:run-slice` on a slice, or which ran `plan_loop.py` or
    `run_loop.py` on it. The stage comes from the command, else from the loop, with `run_loop`
    first.
  - **R4:** an interactive session with `/dev:close-out`, or whose first prompt says close out.
    Its stage is `close-out`.
  - **R3:** a headless session (`sdk-cli`) that no state file records, whose first prompt names
    the slice, with the role and phase that the prototype's `R3_ROLES` read from it.

  The spec repo of a name with no repo is the one the session's working directory names, as
  `spec_of_cwd` gives it. The transcript's `adopted_group` is its slice's group. Each R2 to R4
  slice name goes into the stamp's `<named>`.
- **R5 is open** (O6): the triage session, found by the commit that added the slice's `slice.md`.
  Until it is ruled, none (`labeller_records.TRIAGE_SESSIONS`, off).

## Test Runs and CI Builds

**A Test Run of a Tool Call.** A foreground Tool Call of the class `test_suite` whose result shows
a test runner's summary is one Test Run per suite. A `kc project test` that runs several
components is one per component. A background run, a result saved to disk with no summary in what
the model saw, and a result with no summary give none. So does a `kc` component whose output
holds no runner's count. A summary whose component head a `tail` cut off is `--project`'s
component where the command names one, else it is dropped. Each Test Run takes these fields:

- `suite` is the Test Suite's code: `<repo>/<component>/<verb>` for `kc project`
  (`PilotApp/backend/test`), else `<repo>/<runner>`. `<repo>` is the checkout the command ran in.
  The suite's name in `test_suites` is the same words with spaces, `PilotApp backend test`.
- `passed` is whether the suite's summary has no failure.
- `tests` is the summary's count. A plain `go test` prints no count of tests, so without `-v` it
  counts the packages.
- `retries_allowed` is the retries the command's flag shows (Playwright's `--retries=<n>`,
  pytest's `--reruns`, vitest's `--retry`), else those the output shows, as the detect-flakes
  mode's reruns, else none.
- `started_at` and `ended_at` are the call's request and result times.
- One Test Failure is made per test the summary names as failed or flaky, with whether it was
  `flaky` and its attempts: the output's count, else the retries allowed plus one, else 1 (2 for
  a flaky test). A Test is its runner's own name: a pytest node id; a Playwright file and its
  titles, `file › title › title`, with no `:line:col` and no `[project]`; a Go test as
  `<package>.<Test>`.

Part 3 pins the summaries this reads (pytest, Playwright, vitest, `go test`, `node --test`, and
kc's own per-component lines) with fixtures, one for each runner.

**A Test Run of a Work Unit**, from the driver's records. It is one per `verb: test` result of a
sweep (`sweeps/r<n>.json`'s `results`), run by the sweep's unit, and one per `projects` entry of a
phase gate's record (`gates/P<id>_gate_<n>.json`), run by the gate's unit. It takes these fields:

- `suite` is `<repo>/<component>/test`. The repo is the result's `repo`, or for a phase gate the
  base name of `state.json`'s `phases[<id>].landed.root`, else of its `target`. `outcome` gives
  `passed`.
- `started_at` and `ended_at` come from the record. A sweep's result ended at the sweep's
  `ran_at` and started its `duration_s` before.
- No Test Run comes of `nothing_ran`, of a sweep result marked `reused`, or of a gate's
  `spec_check`, `migration_check`, `waived` or `covered` entries.

The records hold no count of tests, and Test Run's `tests` is required. Whether these Test Runs
exist before something gives that count is open (O4). Until it is ruled, they are not handed
(`labeller_records.DRIVER_TEST_RUNS`, off). Old slices have no gate or sweep records at all
(runner-state.md, "not the gate and sweep records").

**CI Builds** come from the wait (F152.10; AIWF-195). A Tool Call of the class `ci_wait` is read
like this:

- The command gives `job` (the positional) and the commit (`--hash`). A `--deploy` or `--buildnr`
  wait names no commit.
- The summary that `track_build.py` prints to stdout under `=== Build tracking summary ===` gives
  the rest. It reaches the transcript in the call's own result, or for a background wait in a
  later Tool Call's result. That later call is one that reads the output file its task
  notification names or the target of the wait's own `>` or `tee`, or `TaskOutput` or
  `BashOutput` with its task's id. Failing those, it is the latest unmatched background wait on
  the same job in the same Launch.
- Each table row is one CI Build, by `job` and `number`. That includes the pipelines the build
  triggered, which are rows of the same table, each with a CI Wait from the same Tool Call.
  - `result` is the row's word, as a `build_result`.
  - `queued_at`, `started_at` and `ended_at` come from the row's `↳ queued … started … ended …`
    line (DI-42, 2026-11-15). A `?`, or a summary from before DI-42, gives none.
  - `commit` is the `--hash`, for the row whose job the command named, a build that superseded
    the first one included.
- **`deployed_at`** goes on the build that a handoff heading of the `=== Argo CD follow ===`
  section names (`… pushed to main, pins … (PilotApp/Build-Main #180)`), where that section's
  `Result:` line opens `rolled`. It is the moment the wait returned (database.md, CI Build; O5,
  settled): for a background wait its task notification's time, or the reading call's result time
  where the summary was read before the notification came. DI-42's `↳ sync …, roll ended <t>` is
  read and not taken.
- A wait whose summary never reached the transcript makes no CI Build and no CI Wait. Its Tool
  Call keeps `ci_wait` and its run time. Neither does a run that exited before its table: no build
  appeared, or `--help`.

## File classes

`classes` classes every File the collector holds, from its repository's name and its path alone,
whoever changed it (F158.5; assertion 581).

```json
{"contract": 1, "home": {…}, "files": [["PilotApp", "backend/app/api/projects.py"], …]}
```
```json
{"contract": 1, "version": "…", "file_rules": "<digest>", "classes": ["code", …]}
```

The classes come back in request order.

**The rules, first match wins.** A project's own rules go first. They are `projects/<repo>.json`'s
`file_classes`, in their order, copied from its `.aiworkflowrc`, in the grammar of
[project-contract.md](project-contract.md) § File classes. A pattern's leading `/` is stripped,
every pattern being read from the repository's root already. A rule of an unknown class, or with
no paths, is skipped. The starting list follows in this order, from
`PilotAppSpecs/tools/cost-dashboard/dispatch-work.md` §7 with AIWorkflow's rule added (t17 D2):

| # | Class | Paths |
|---|---|---|
| 1 | `generated` | `*.lock`, `pnpm-lock.yaml`, `package-lock.json`, `*.snap`, `**/generated/**`, `*.gen.*` |
| 2 | `spec` or `record` | in a spec repo (below): inside a slice folder, `*.md` is `spec` and anything else `record`; anywhere else in it, `spec` |
| 3 | `test` | `**/tests/**`, `**/test/**`, `*.spec.ts`, `*.test.ts`, `*.test.tsx`, `test_*.py`, `*_test.py`, `*_test.go`, `conftest.py` |
| 4 | `code` | in the repository `AIWorkflow`: `plugins/**` |
| 5 | `docs` | `*.md`, `README*`, `CHANGELOG*` |
| 6 | `code` | everything else |

- **`**/` matches zero or more segments**, so `**/generated/**` holds `generated/x` too.
- **A spec repo** is a name among the run records' `runs/<spec-repo>/` folders or the groups'
  `spec_repo`. A slice folder is a path segment matching `\d{3}[a-z]?_[a-z0-9_]+` directly under
  the repository's root `slices/`, or under
  `slices/<backlog|active|completed|archive|cancelled|deferred>/`.
- **AIWorkflow's rule** stands where the table has it, after the tests and before the docs (O7,
  settled), so `plugins/dev/tools/test_*.py` stays `test` and the skills and agents are `code`.
- **`file_rules`** is the digest of the effective rules: the version, every `projects/*.json`'s
  rules (the rules alone, not the file's `updated_at`) and the set of spec repos. `stamps` answers
  it too, at the cost of a stat and a few small reads. The record has every File classed again at
  every walk, with no stamp on the File (decision 79.33). That is the same as reclassing every File
  whenever `file_rules` differs from the one the collector last classed under, and classing a new
  File as it appears. After a restart the collector does not know which `file_rules` Pilot's classes
  were made under, so it reclasses every File once.
- **The cost.** Each repository's rules are compiled to one regular expression per rule, so a
  File costs one match per rule.

## The replay check

A full replay is the specification: labelling a file in parts, cut after any Call, gives what
labelling it whole gives (F152.16). The check is part of the labeller.

**The corpus tests.** Their transcripts are invented, built by the engine suite's fixture builder
(`Script` in `test_labeller_engine.py`), and no real transcript is committed. Each test labels a
transcript whole, then grows the file the way the collector meets it: labelled whole as it stood
at a cut, then from the boundary and checkpoint that handed back at every later cut, an answer
`whole` labelled whole again. It merges the parts the way Pilot does, the labels before the
boundary kept and those from it on replaced (assertion 561), and compares the merge with the
whole, label by label. The cuts fall just before every Call's first line, one at a time, and at
two and three random bytes in turn, inside a line still being written included.

- **`test_labeller_engine.py`** holds the engine to it on a corpus that exercises each class and
  wait cause, an open background CI wait that is matched, one left unread and one past its 20
  Calls, a late tool result (`behind`), a call added to an earlier message, several Launches,
  `<synthetic>` Calls and a sub-agent, and on random sessions. Part 2's tie and Part 3's rules are
  stood in for there, and one test runs Part 3's own.
- **`test_labeller_check.py`** runs it on real modules throughout, over an invented home: a
  dispatch with a sub-agent, a stage's own session, an old session adopted by its first prompt
  and a session nobody knows, beside run records with a slice's plan and run, its gates and
  sweeps, `slice.json`, a groups file and a project's file rules. It runs `check` over that home,
  and every verb as a subprocess, JSON both ways: `info`, `vocabularies`, `stamps`, `label` whole
  and then appended with the checkpoint handed back, `classes` and `check`.
- **The stamp** is pinned in both `test_labeller_records.py` and `test_labeller_check.py`: a
  rewrite of `state.json` that changes no derived fact changes no stamp, and one that changes a
  unit's row changes the stamp of every transcript that names the unit and no other.

**The command**, `labeller.py check`, runs the same comparison over real transcripts on a home.
It takes flags, not a request on stdin:

```
check [--projects DIR] [--plugins DIR] [--data DIR] [--sample N] [--cuts K] [--every N]
      [--seed S] [--context FILE] [--paths FILE] [--] [PATH…]
```

- **Which transcripts.** The `PATH`s given and the lines of `--paths`, absolute or under
  `--projects`, else a sample of `N` (default 50; 0 for every one) drawn with `--seed` from the
  main threads (`<project>/<session>.jsonl`) and sub-agents (`agent-*.jsonl` under
  `<project>/<session>/subagents/`) of `--projects`. A relative path starts with a project
  folder's `-`, so it goes after `--`. A path outside `--projects` is refused.
- **The home.** `--projects` and `--plugins` default to `~/.claude/projects` and
  `~/.claude/plugins`; `--data` names the run records' folder in place of the plugins' own, as
  `home.data` does.
- **The cuts.** A transcript of fewer than `--every` Calls (default 200) is cut just before every
  Call's first line, one at a time; a longer one at `K` of them, drawn at random. Then `K` runs
  (default 5) of one to three random bytes each.
- **It stands in for the collector.** It reads the Calls as § Names both sides compute gives them,
  treats a main thread as one Launch, since the collector's Launch rule is not the plugin's, and
  takes a sub-agent's `agent_type` from its `agent-*.meta.json`. Launch-dependent labels are held
  by the corpus, whose Launches are explicit. `--context` is a JSON file of conversations, shaped
  as in § What Pilot hands with a conversation, a list or `{"pilot": {"conversations"},
  "conversations"}`. Without it, every conversation has none.
- **What it compares.** Each merge with the whole, label by label, and the rows Pilot writes by
  their keys (the units, Test Suites and CI Builds), the last one written of each. Then one
  `stamps` call over every transcript labelled, each with its label's stamp held, which must give
  every stamp back.
- **The report**, for a person: a line per transcript, `ok`, `differs` with the cut and the first
  label that differs, or `error`, with its Call count, its cuts and the `why`s of any answer
  `whole`; a `stamp` line per stamp not given back; then the count of each, and the timings of
  whole labelling (seconds per MB, the largest file), of appended labelling (median, p95, max),
  and of the `stamps` call and the run records' cold load.
- **Exit codes.** 0 when every transcript agrees and every stamp is given back, 1 otherwise, 2 for
  arguments it cannot use.

It writes nothing: a cut is the file read as it stood when it was that long. Run it after any
change to a rule, and on the home before a release.

Pilot's own net is the replay at rest (F152.16), which logs any settled row that a whole replay
changes. Such a row is a defect of the labeller's and gets a card here, with the transcript's
check as its reproduction.

## Where it departs from the prototype

- **One engine, and labels the collector can join.** The prototype replayed each transcript whole
  through `turn_profile.analyse` with a variant per flag set. The labeller classes each transcript
  once, under its role's flags, and labels by the collector's Call ids.
- **Loop commands as `turn_profile` reads them.** The prototype's `LOOP_RE`
  (`run|wait|stop|status|resume`, with no quotes and no `long_run`) is not used. R2 reads the
  loops with `turn_profile`'s `WORKFLOW_RE` and `_workflow_op`, which know `fixes`, `progress` and
  a quoted path.
- **R2 prefers `run_loop`.** The prototype sorted on the verb (`x[1] != "run"`), not on the loop.
- **Completion consults by `site`.** Where a row has a `site`, every `completion` consult is one.
  The prototype took only the first consult with no phase.
- **No work types.** `ROLE_WORK_TYPES`, `SUBAGENT_WORK_TYPES` and `subagent_work_type` have no
  place in the record. A Work Unit carries the history's `role`, and a sub-agent its
  `agent_type`, a fact. With them goes the test-fixer's double work type, `test-fixer` as a row
  and `test` as a sub-agent.
- **Ids by key.** No uuid5 project or session ids, and no synthetic work items or turns: an
  adopted Project is Pilot's, found by its group's key (F152.8).
- **Tied by the run records.** The prototype placed a loop conversation on a Pilot Turn by time
  (`TURN_SLACK`, `BEFORE_FIRST_TURN`, `AFTER_TURN_END`). That placement is now Pilot's own, its
  Launch's `session` (assertion 538). The labeller only maps a Launch to its dispatch row.
- **R5 dropped until ruled** (O6): it needs the spec repos' git history, which the labeller cannot
  read.
- **The clarification keeps the prototype's split.** It is the slice's, not the stage's, though a
  Launch is placed by its Session's `created_at` where the prototype used the Turns' times.

## Open points

Each changes a figure the dashboard can show, and neither the record nor the rulings settles it.
Each is the operator's to rule, and the ruling is pending: PilotAppSpecs
`tools/cost-dashboard/asks/t17-labeller-2.md` puts them as D5 to D10. Until a point is ruled, the
build gives its default, set in one place in the code, as each item says.

- **O1. Unit Outcome for the history's other words** (D5). These are the plan-reviewer's `go` and
  `questions`, the plan-writer's `questions`, the test-agent's `clean` and `findings`, the
  test-fixer's and the old code-tester's `clean` and `issues`, every role's `blocked` and
  `session_limit`, the gates' `nothing_ran`, and the consults' actions (`complete`, `proceed`,
  `amend`, `appended`, `merge`, …). The choices:
  - fold them into the record's six (`go` as `signoff`, `questions` as `question`, `clean` as
    `done`, `findings` as `issues`);
  - declare each word as a value of its own;
  - leave them with no outcome.

  The build gives no outcome (`labeller_records.OTHER_OUTCOMES`, empty).
- **O3. The gap before a later Launch of a Pilot conversation** (D6). This is a person answering,
  Pilot holding the session, or Pilot's own nudge. Telling them apart needs what the record does
  not hand the labeller: each Session's Holds, and its Turns' `cause`. The choices:
  - Pilot hands both, and the labeller gives `hold` where a Hold overlaps the gap, else `person` for
    a Turn a person caused, else `driver`;
  - the labeller gives `person` to all of them;
  - none.

  The build gives none (`labeller_engine.O3_LATER_LAUNCH_OF_PILOT`).
- **O4. The driver's Test Runs have no test count** (D7). The choices:
  - the driver records each suite's count in the gate and sweep records (an AIWF card);
  - the record makes Test Run's `tests` optional (a P card);
  - no Test Run from the driver's records.

  The build gives the third (`labeller_records.DRIVER_TEST_RUNS`, off; on, they are handed with
  `tests` null).
- **O6. The triage sessions of old slices (R5)** (D8). The choices:
  - the seed writes each old slice's triage session into `slice.json`, found as the prototype did
    from the commit that added `slice.md` (an AIWF card for the seed);
  - they stay on no project.

  The build gives the second (`labeller_records.TRIAGE_SESSIONS`, off; on, it ties the session
  ids `slice.json`'s `triage_sessions` lists to the slice's `triage` stage).
- **O8. `gate_red`'s `is_error`** (D9): whether a red gate counts among the error events. The
  build declares it null (`labeller_vocab.GATE_RED_IS_ERROR`).
- **O9. `no_git_add_all` outside a shared tree** (D10). The record's sample breaches it "in a
  shared tree", and the labeller cannot tell which trees kc marks shared. The choices are any tree
  or only a spec repo's. The build counts any tree (`labeller_tools.ADD_ALL_ONLY_IN_SPEC_REPO`,
  off).

**Settled.** O2: a driver's gate is a Work Unit of the kind `gate`, gate ⊂ phase and gate ⊂
stage, carried by the anchor (§ Work Units). O5: `deployed_at` is the record's, the moment the
wait returned (`labeller_tools.deployed_at`). O7: AIWorkflow's `plugins/` rule stands after the
test rule and before the docs rule (§ File classes).

## Modules and build parts

`plugins/dev/tools/` is no package. The labeller is a script and its sibling modules, each with a
`test_*.py` beside it under the repo's runner conventions:

| Module | Holds |
|---|---|
| `labeller.py` | the verbs, the request and answer shapes, the contract check, the refusals, the stamp's text and its context inputs, the JSON Lines stream, the batch loop |
| `labeller_vocab.py` | every declared list as data: § The vocabularies, the nestings, `declarations` |
| `labeller_records.py` | the run records: the index and its blob, ties, Work Units and their keys, attributes, outcomes, measures and anchors, the driver's Test Runs, the groups and adoption, the stamp's record inputs |
| `labeller_tools.py` | the rules of one Tool Call or prompt: command class, effects, rule breaches, the Test Run summaries, `track_build.py`'s summary, digest sections. Pure functions of the call, its result and a little context |
| `labeller_engine.py` | the transcript engine: reading from a byte, matching the handed Calls, the classifier steps, wait causes, Segments, open stretches, settledness, the boundary and the checkpoint |
| `labeller_files.py` | § File classes: the grammar, the starting list, the spec repos, `file_rules` |
| `labeller_check.py` | § The replay check's command: the transcripts as the collector finds them, the cuts, Pilot's merge, the comparison, the report |

**The interfaces between them**, as built:

- **`labeller.py`** calls `label_batch(request, records, write_line, index=None)`,
  `stamps(request, records, index=None)` and `labeller_files.classify(files, rules)`, the index
  being the blob `Records.load` handed back. It caps the index handed out at 16 MiB. It hands
  `label_one` the request's transcript with `session_id`, `file` (its absolute path), `stamp`,
  `conversation`, `pilot` and `restamp(named) -> (stamp, tie)` added; the slices a file names reach
  `records.tie` as the transcript's `named`.
- **`labeller_records.Records`**: `load(data_dir, blob=None) -> (records, blob)`;
  `tie(conversation, transcript) -> Tie`; `unit_rows(keys)`; `stage_rows(stage_key)`;
  `test_runs(stage_key)` and `driver_test_runs(stage_key)`; `groups()`, as `vocabularies`
  declares them; `use_pilot(ids)`; `needs_facts(conversation, transcript)` and
  `named_from_facts(facts)`, beside the module's `read_facts(path, size=None)`; `spec_repos()`;
  `project_rules`; `stamp_inputs(tie, context)` and `stamp(tie, context)`, the context being
  `{"conversation", "transcript", "pilot"}` with `pilot` a frozenset.
- **`labeller_tools`**: `tool_labels(name, input, result, ctx)`, `ctx` a `ToolCtx`, giving the
  labels and, for the engine, `ci_wait`, `ci_summaries`, `background` and `reads`;
  `digest_sections(prompt_text)`; and `ci_builds`, `parse_track_summary`,
  `parse_test_summaries`, `command_class`, `repo_of`, `result_text`, `deployed_at` and
  `gate_red_event`. It reads commands through `turn_profile`'s private shell helpers (`_bash`,
  `_split`, `_unwrap`, `_blank`, `_word_end`, `_unquote`, `_verb`), so a change to them is a
  change to the labeller and runs its suites.
- **`labeller_engine`**: `label_one(item, tie, records)`, raising `LabelError(code, message)`. It
  steps `turn_profile.TurnClassifier(reads_are_work, plan_is_edit, first_edit_turn, state)` with
  `.step(turn, last)` and `.state()`, `first_edit_turn` being `"auto"`, a turn or none, and reads
  through `turn_profile.Replay(first_i)` with `.feed(record)`; `classify_turns` and `replay` are
  built on them and answer as before. An item's `size`, which no request carries, reads the file
  as it stood at that byte, for `check`.

**The build parts.** There were five: the command and the declarations (`labeller.py`,
`labeller_vocab.py`, `labeller_files.py`), the run records, the Tool Call rules and the engine,
built beside one another against the interfaces above, and last the check and the release:

- the corpus tests and `labeller.py check` (§ The replay check);
- the timings against § The stamp's targets, on the home;
- `CLAUDE.md`'s tool map and `README.md`'s lines;
- the plugin version and changelog entry, once the open points are ruled.

Slice 052's planning reads this page as released. PilotApp's stub labeller (F122.5) answers the
same shapes.
