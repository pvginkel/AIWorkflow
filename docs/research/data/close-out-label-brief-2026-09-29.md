# Labelling brief — close-out entries, six attributes

You label entries of close-out reports. A close-out report is one Markdown file per finished
piece of work (a "slice"); the agents that did the work appended entries to it for whatever
they noticed and did not act on. Each entry is a `### <id> — <headline>` heading (ids are a
letter and a number: `A1`, `N2`, `B3`, `Q1`, `S7`), a body, and three closing labels:
`**Consequence:**`, `**Provenance:**`, `**Disposition:**` (blank).

Your labels are research data. They will be compared with what the operator later decided
about each entry, which you cannot see. Label what the entry says, not what you think should
be done with it. You have the report text and nothing else: do not open any repository, do not
search for the code. Where the entry does not let you tell, the answer is `unknown` — that
value is as useful as any other, and a forced guess spoils the data.

## What to label

Every **live** entry of every report in your batch: every `### <letter><number> — …` heading
that is not struck. A struck entry has its heading in `~~strikethrough~~` or sits inside a
folded `<details>` block of struck entries; skip those. A heading without an id in that form
is skipped too. Headings inside a code fence are quoted text, not entries.

## The six attributes

**1. `kind`** — what the entry is. One of:

- `action` — something only the operator can do (a push, a deploy, a confirmation).
- `event` — something that happened during the run, recorded as such.
- `question` — asks the operator to choose between options or to rule on a convention.
- `idea` — proposes new or changed behaviour of the product, removing a feature, or a
  redesign: a product call.
- `prose` — text is wrong, stale or missing: documentation, a code comment, a docstring, help
  text, a message's wording. The code's behaviour is not in question.
- `test-gap` — the whole claim is that a test is missing, pins nothing or cannot fail, while
  the code it would guard is right today.
- `defect` — the code, configuration or deployed system does something wrong today, however
  rarely.
- `hardening` — the code is right today; the entry wants it guarded against a condition that
  does not occur with the code as it is (a future edit, a second caller, drift between two
  copies, a gate that does not exist yet).
- `cleanup` — a refactor, simplification or consistency change without a change in behaviour.
- `slice-input` — input for work that has not run yet: it names a later slice, phase,
  migration or plan that has to take it into account.

If two fit, take the first that fits in this order: action, event, question, slice-input,
test-gap, prose, defect, hardening, idea, cleanup.

**2. `trigger`** — what has to happen for the problem the entry describes to show. One of:

- `normal-use` — it shows on a path that ordinary use takes; nothing special is needed.
- `ordinary-condition` — it needs a condition that ordinary operation does produce now and
  then: a restart, a second environment, a slow or briefly absent dependency, an upgrade, a
  particular but legitimate input or configuration.
- `fault-or-coincidence` — it needs a fault, a narrow timing window, a misconfiguration, a
  misuse, or several conditions together.
- `future-change` — it cannot show with the code as it is; somebody has to change something
  first.
- `none` — there is no problem that could show: the entry is about something with no effect.
- `unknown` — the entry does not let you tell.

**3. `impact`** — what the operator or a user would experience when it shows. One of:

- `wrong-or-lost` — a wrong result, lost or corrupted data, an exposure.
- `broken-or-stuck` — a flow fails or stays stuck until somebody intervenes.
- `misleading` — a wrong or confusing message, status or document; whatever went wrong
  corrects itself or has no further effect.
- `none-observable` — nobody would notice.
- `unknown` — the entry does not let you tell.

For `test-gap`, `hardening`, `cleanup`: label the trigger and impact of the problem the entry
wants to prevent (usually `future-change`), not of the missing test itself.
For `action`, `event`, `question`, `idea`, `slice-input`: use `none` and `none-observable`
unless the entry describes a problem; then label that problem.

**4. `fix`** — what is decided about the change. One of:

- `one-edit` — the entry states or plainly implies the exact change, in one place: the text
  that should read otherwise, the guard that is missing, the status code that should be
  another.
- `known-several` — the change is known and mechanical but in several places.
- `design` — a choice with consequences is open, or the change adds behaviour: a new code
  path, a new piece of state, a new process, a new gate or test harness.
- `unknown` — the entry does not say what the fix would be, and it is not plain.
- `na` — nothing to fix (an action, an event, a question).

**5. `sensitive`** — `yes` if the change would touch concurrency or timing, the layout of
stored data, a wire or API contract between components, or authentication and secrets;
otherwise `no`. `na` where `fix` is `na`.

**6. `basis`** — where your trigger and impact labels come from. One of:

- `stated` — the entry itself says what has to happen and what is then experienced (usually on
  its `Consequence:` line).
- `partly` — it says one of the two, or says it vaguely ("could", "may in some cases").
- `inferred` — you derived both from the body; the entry does not say.

## Output

For each report, one JSON file in `/tmp/co/labels/out/`, named as the report file with `.json`
in place of `.md`. One object: entry id → the six attributes. Nothing else in the file.

```json
{
  "B1": {"kind": "defect", "trigger": "fault-or-coincidence", "impact": "misleading",
         "fix": "design", "sensitive": "yes", "basis": "stated"},
  "S4": {"kind": "test-gap", "trigger": "future-change", "impact": "broken-or-stuck",
         "fix": "one-edit", "sensitive": "no", "basis": "partly"}
}
```

Use exactly the values listed above, spelled as above. Write each report's file when you have
labelled that report, before you read the next one, so that nothing is lost if you stop early.
Read the reports whole, two or three per turn; do not grep them for headings and label from
the headings alone — the body and the Consequence line are what the labels rest on.

When every report in your batch has its file, validate them with one command: each file
parses as JSON, every value is in its vocabulary, and the set of ids equals the live entry
ids of the report. Fix what the check finds.

## Your final message

Under 150 words: how many reports and entries you labelled, which reports (if any) you could
not finish, and the two or three attribute decisions you found hardest to make from the text —
they tell us which definitions are not sharp enough. Your labels will be reviewed and scored;
say plainly where you were unsure.
