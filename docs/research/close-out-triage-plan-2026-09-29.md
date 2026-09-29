# The close-out report, triaged at the source — plan (2026-09-29)

Companion to [close-out-read-2026-09-28.md](close-out-read-2026-09-28.md) (the read; this plan
does not restate it) and successor to
[close-out-rework-plan-2026-09-29.md](close-out-rework-plan-2026-09-29.md), which it supersedes
before that plan was ruled. It came out of the operator's discussion of the read on 2026-09-29;
§ 2 has their words, § 3 what was computed during it.

**Status: for the operator's ruling; one section open.** Nothing in the plugin changed beyond
0.9.56. § 5 has the decisions that are the operator's, each with a default. § 4.4, the
treatment of potential improvements, is being worked out with the operator and is not settled;
"go" builds everything else as written.

**The plan in short.**

1. **The author of an entry says what it is.** Every entry carries labels: what kind of thing it
   is, what has to happen for it to show, what is then experienced, what is decided about the
   fix, where the fix lives. Authors write these facts in prose already — 87 % of the entries
   state them — and now give them in a vocabulary the tool checks (§ 4.2).
2. **The policy is the operator's and lives in the tool.** A table routes every entry from its
   labels: to the operator, to the wrap-up phase, closed, or the record. No author chooses a
   disposition (§ 4.1, § 4.3).
3. **An action, a decision and anything severe always come to the operator** — in full, first in
   the report, their labels in words on the entry. There is no list to read before the entries.
   In the replay that is a median 3 entries of the 11 a report hands over (§ 3.4).
4. **A wrap-up phase takes the rest**, after the doc phase: it fixes what is decided and safe,
   asks for a card where a likely problem is more than it can fix responsibly, and leaves closed
   what the table closes. One agent, two callers — the close-out session first, the driver once
   a replay has priced it (§ 4.6).
5. **The text-only sorter goes.** Replayed against the rulings that are the operator's own, the
   labels and the table keep 92 % of their picks and close 20 % of the entries; the sorter of
   the superseded plan kept 83 % (§ 3.2, § 3.4).
6. **Three versions, in this order**: 0.9.57 the labels, the routing and the report's shape;
   0.9.58 the wrap-up agent with the close-out session as its caller; 0.9.59 the driver
   dispatches it (§ 6).

## 1. What changed since the superseded plan

That plan put one agent after the run to guess, from the report's text, what the operator would
rule. Three things the operator said on 2026-09-29 move the design to the other end of the
report:

- the rulings they hand over are not their pattern, so a sort trained and scored on all rulings
  was partly scored against its own kind (§ 3.2);
- losing an entry of the lower tier is not a problem — what must not happen is that an agent
  wants their eyes on something and they do not see it;
- the entries read as a dump, "they aren't questions": the author should triage what it
  reports.

## 2. What the operator said

Their words, in order.

On the Focus line:

> I don't read it, at all. I find it interesting you found that it doesn't really impact my
> rulings. It's not a result of me not reading them though. I judge the items at their merit.
> It means the focus line isn't correct a lot of the times.

On which rulings are theirs:

> I'm not asking about the current close out rules, right? I wrote those up in 5 minutes. What
> I'm asking is whether new instructions, based on my ruling history, would give enough of a
> steer?

> I think roughly 1/3 of the time the reason is that I've already seen that there is little to
> progress. The rest, 2/3, is because I'm doing the third or fourth close out report in a
> sitting and I'm fed up with them. What I'm saying is that my handling of auto close out is not
> representative of my ruling pattern. What you could include though is where I do half, and ask
> the agent to take over. In those cases I really don't know (other times I'll ask in the
> disposition I need help; you've seen this) and I would have accepted closing them all.

On what to guard, the two tiers and the wrap-up phase:

> I don't think there is any problem. There will always be bugs. What I would guard against is
> an agent trying to get my eyes on something that I then don't see. … So it's not immediately
> obvious what it feels is important I look at. I think this is far more important, that we
> find a way to get that signal through also.

> On the one hand we can have labels like: decision, needs ruling, risk. Those should just
> always come to me. On the other end of the scale you can have labels like: test gap,
> potential bug, prose gap. Of the latter category I would not feel bad if none were progressed.

> one of the options for where we go from here is that everything in the second category goes
> into a wrap up phase, maybe even after the doc phase. It would automate what I do today ("fix
> inline please"). … The instructions would be to fix what it feels confident to fix, request
> to card likely issues that are too complex to solve in the sweep phase, and the rest we just
> close.

The policy:

> We really shouldn't give everything to the sweep to progress. We do need to find a way to trim
> with some confidence the items I think could be closed. Now this isn't really fair, because
> there'll be quite a few items I close because I don't feel like putting in the effort to
> progress them.

> * Prose (docs and code comments) and nits that can be fixed safely with a simple code fix can
>   of course always be progressed.
> * Bugs, regardless of whether or not they're likely, that are easy to fix (missing guard,
>   additional exception checked, changed HTTP status code, i.e. something with an obvious fix)
>   can always be progressed.
> * Everything that's more complicated is decided on how likely it is to cause problems. If the
>   answer is: modestly to very unlikely, close them. Otherwise: fix them in the sweep if that
>   can be done responsibly; otherwise card them.
>
> And we'd have to do a similar categorization for suggestions. Risk based, right?

On the author's part:

> it's very important that the labels are decided right. I feel right now the close out report
> is just a dump of thoughts and ideas. They aren't questions. Is that fair? Maybe. But the
> agent isn't really taking responsibility for what it's reporting. "I saw this; not sure what
> you want to do with it." What if we ask it to triage the item itself?

On severity, after the replay's first table had closed a defect graded major:

> High severity needs to come to me, even if it's very unlikely. Does it matter it's security
> related? I don't really think so. Low risk of catastrophic data loss should also come to me.
>
> It would of course help a lot if this information is clearly visible, right?

On where they read it:

> I don't read the close out card body, or the head of the report. A list of entries is enough
> for me.

On Suggestions:

> I do feel there are roughly two categories: should be fixed, and potential improvement. The
> first are kind of in the bug category. Or at least, they can be handled as such. The second
> category should get a different treatment. I want them labeled also, but of course with
> different attributes.

**Ruled by these words:**

- The Focus lines go: they are not read.
- No list at the head of the report and none in the close-out card's body: they are not read
  either. The report is its entries.
- The rulings that count are the operator's own — a session they ruled themselves, and the
  entries they named before handing over the rest. Rulings taken from a sheet do not.
- The policy of the three bullets, for Bugs and for the Suggestions that should be fixed.
- What is severe comes to the operator at any likelihood, whatever its subject.
- The author labels its entry, in a form a tool can parse, and the labels are in plain view.

**Not ruled:** this plan; that the wrap-up may fix before the operator has ruled (D1 — their
proposal implies it, the contract forbids it in words of 2026-08-17, so it is asked plainly);
the other decisions of § 5; the labels and the route of a potential improvement (§ 4.4). They
called the wrap-up phase "one of the options".

## 3. The evidence

Computed on 2026-09-29 from the read's corpus (99 reports, 1,429 entries). "Progressed" is
carded, fixed or folded, as in the read. Sources are at the end of the section.

### 3.1 The Focus line, by place

Bugs and Suggestions the operator ruled, by where the entry stands in its section's Focus line.
Because the line was never read, this is agreement between two judges, not anchoring.

| place in the Focus line | entries | progressed |
|---|--:|--:|
| named first | 159 | 60 % |
| named second | 129 | 46 % |
| named third or later | 346 | 36 % |
| not named | 193 | 36 % |

1. **Its first pick is good and nothing else in it is.** In the 100 sections where the operator
   progressed some entries and closed others, the first-named entry was one they progressed in
   71 %; an entry at random 45 %, the highest grade 58 %.
2. **It cannot select.** It names 76 % of the entries, and every entry in 59 % of the sections
   with three or more. 72 % of the operator's picks are not the first-named entry.
3. **The replayed sorter read it.** The hand-over snapshots hold the Focus lines, so the read's
   87–89 % was measured with the doc-writer's first pick in view. This plan has no sorter; the
   point stands for any later replay on those snapshots.

### 3.2 Whose ruling, and the sorts scored against the operator's own

Every ruled entry by who decided its fate, from the read's session coding.

| whose ruling | entries | progressed |
|---|--:|--:|
| the operator's own: a session ruled directly, or an entry they named | 264 | 48 % |
| an entry they asked advice on | 39 | 51 % |
| taken from a sheet | 276 | 30 % |
| the rest of a mixed, handed-over or auto session | 243 | 27 % |
| no coded session | 207 | 36 % |

The two sorts of the read on its 30 held-out reports, scored against the first row only
(97 entries, 41 picks):

| | the skill's current rules | the read's revised rules |
|---|--:|--:|
| picks kept | 63 % | 83 % |
| entries the sort closes | 51 % | 31 % |
| … of which the operator had progressed | 31 % | 23 % |
| work it proposes that the operator had closed | 38 % | 45 % |
| the disposition itself matched | 62 % | 54 % |

4. **The read's 9 % was a sheet's number.** "What the revised sort closes is progressed at 9 %"
   holds over all rulings; against the operator's own it is 23 %, and 12 % on the six reports
   they ruled whole (where the sort kept 85 % of the picks against 75 %).
5. **The revised rules learned partly from the wrong teacher.** Of the 94 lost picks they were
   derived from, 34 were the operator's own rulings; 30 came from a sheet or a handed-over
   remainder, 28 from sessions never coded, 2 from advice.
6. **Only the misses were studied.** Nobody read the false alarms, and close to half of the
   work the revised sort proposes is work the operator closed.

### 3.3 The labels against the operator's own rulings

Four Opus sub-agents labelled every live entry of the 49 hand-over snapshots the operator ruled
by their own reading — 580 entries, from the text alone, dispositions not visible — on six
labels. Two snapshots share a slice number and one holds no entry ids, so the tables count 47
reports and 561 entries handed over; 234 of them are the operator's own rulings.

| label | value | entries | progressed | carded or folded | fixed |
|---|---|--:|--:|--:|--:|
| trigger | normal use | 68 | 68 % | 22 % | 46 % |
| | an ordinary condition | 35 | 54 % | 29 % | 26 % |
| | a future change | 59 | 46 % | 29 % | 17 % |
| | a fault or a coincidence | 37 | 35 % | 24 % | 11 % |
| | none | 32 | 16 % | 6 % | 9 % |
| fix | one known edit | 88 | 59 % | 17 % | 42 % |
| | known, several places | 27 | 56 % | 30 % | 26 % |
| | needs design | 55 | 42 % | 33 % | 9 % |
| | unknown | 17 | 41 % | 29 % | 12 % |
| kind | prose | 63 | 68 % | 10 % | 59 % |
| | test gap | 26 | 42 % | 38 % | 4 % |
| | defect | 40 | 38 % | 28 % | 10 % |
| | hardening | 20 | 35 % | 10 % | 25 % |
| | event | 18 | 11 % | 11 % | 0 % |
| sensitive area | no | 143 | 57 % | 26 % | 31 % |
| | yes | 44 | 34 % | 20 % | 14 % |

7. **The trigger orders the rulings** from 68 % to 16 %, and **the fix label separates fixing
   from carding**: one known edit is fixed inline at 42 %, a fix that needs design at 9 % and
   carded at 33 %.
8. **The authors already know.** The entry itself states what has to happen and what is then
   experienced in 87 % of the cases (490 of 561); the labellers had to answer `unknown` for 4 %.
   Triage at the source is mostly labelling what is written.
9. **`unknown` does not find what the operator cannot judge.** Of the 33 entries they asked
   advice on, 2 carry an `unknown` trigger or impact. A reader commits where the operator could
   not (D7).
10. **The Suggestions are two populations, as the operator says.** Of the 304 handed over in
    these reports the labellers called 172 prose, a test gap or a defect (57 %) — what is
    handled as a bug — and 76 an idea, a hardening or a cleanup (25 %); 36 are input for a later
    slice, 14 a question. Over entries of every kind the operator ruled 40 so labelled
    themselves: 10 carded, 7 fixed, 23 closed.

### 3.4 The policy table against the operator's own rulings

The labels of § 3.3 through the operator's policy, mechanically. Three tables were run: the
three bullets as stated; with impact in the rule and an event that describes a problem routed as
that problem; and with what is severe placed ahead of the easy fix, as the operator then ruled.

| table | picks kept | cards and folds kept | entries closed |
|---|--:|--:|--:|
| the three bullets as stated | 88 % | 82 % | 26 % |
| impact in the rule; events by their problem | 92 % | 87 % | 20 % |
| … and severe ahead of the easy fix | 92 % | 87 % | 20 % |

The last table, by route, against what the operator did (234 entries, 112 picks):

| route | entries | | closed | fixed | carded | folded |
|---|--:|--:|--:|--:|--:|--:|
| to the operator: an action | 14 | 6 % | 11 | 0 | 3 | 0 |
| to the operator: a decision | 22 | 9 % | 9 | 4 | 8 | 1 |
| to the operator: severe, or graded major | 33 | 14 % | 14 | 7 | 11 | 1 |
| to the wrap-up: fix | 87 | 37 % | 34 | 41 | 11 | 1 |
| to the wrap-up: fix, or ask for a card | 9 | 4 % | 6 | 1 | 2 | 0 |
| to the wrap-up: look | 4 | 2 % | 2 | 0 | 2 | 0 |
| input for a later slice | 18 | 8 % | 8 | 2 | 3 | 5 |
| closed | 35 | 15 % | 26 | 2 | 7 | 0 |
| the record | 12 | 5 % | 12 | 0 | 0 | 0 |

Over everything the 47 reports handed over (561 entries, a median 11 a report):

| | entries | | a report, median | max |
|---|--:|--:|--:|--:|
| comes to the operator | 171 | 30 % | 3 | 13 |
| goes to the wrap-up | 247 | 44 % | 5 | 17 |
| input for a later slice | 36 | 6 % | 0 | 8 |
| closed | 72 | 13 % | 1 | 5 |
| the record | 35 | 6 % | 0 | 4 |

11. **The first table closed a defect graded major** (KubeCoder 165 B1): severe in impact, a
    fault for a trigger, a fix that needs design. "Unlikely, so close" cannot be the whole rule;
    the operator ruled the same when asked.
12. **The replay's first tier is wider than the plan's.** Its severe is the label
    `wrong-or-lost`, which holds wrong results beside lost data, where § 4.2's `severe` is
    narrower; and it sent every idea to the operator as a decision — 26 of the 171 — where the
    route of a potential improvement is open (§ 4.4). 171 is an upper bound.
13. **The wrap-up would attempt more than the operator asked for.** It gets 37 % of the entries
    to fix where the operator had a quarter fixed; of those 87 they had 41 fixed, 12 carded or
    folded and 34 closed. Part of those closes were effort, in their own words, so an entry the
    table fixes and they closed is not counted as an error. The score runs one way: what the
    table closes and they progressed.
14. **Rulings taken from a sheet agree more**, as in the read: the same table closes 21 % of
    those 215 entries and 4 % of what it closes was progressed.

### 3.5 The misses

Nine picks the last table closes — seven cards and two inline fixes, none graded above minor:

| class | entries | |
|---|--:|---|
| an event that describes a failing test run, a fault for a trigger | 2 | carded |
| a defect and a test gap that break a flow, a fault for a trigger | 2 | carded |
| hardening and cleanup with slight or no impact | 3 | carded — the operator's own call |
| a defect and a hardening of slight impact, fix needs design | 2 | fixed inline |

Of the 35 closes on the operator's own rulings 15 have an impact that breaks a flow, and four of
the seven lost cards are among them; over all 47 reports that is 31 of 72 closes, 0.7 a report
(D7).

### 3.6 The appended phase

The operator asked what goes into it and whether more should be steered to the report. Every
completed slice with a run state, both projects; a phase is appended when its first executor
round follows the first completion consult.

| slices created | slices | with an appended phase | appended phases |
|---|--:|--:|--:|
| before 2026-08-16 | 76 | 22 (29 %) | 31 |
| since (the bar of 0.5.1) | 96 | 5 (5 %) | 6 |

15. **Before 0.5.1 the consult swept.** By its own summaries about a third of those phases was
    work the plan owed, a third test gaps and a third prose or comment drift — findings a review
    had left unfunded and close-out nits, taken in as "cheaper to fix than to card".
16. **Since, all five are work the plan owed**: a criterion a rebase falsified, a wire-contract
    page the doc phase may not edit, docs owed after a doc phase that died, a ruling implemented
    in half, a ruling no phase owned.
17. **The steering has happened.** What the consult used to take in is in the report now, which
    makes it the wrap-up's input. The two classes the operator named are one: the reviewer
    enters every advisory finding in the report itself.
18. **A price for a small fix phase with a review**: a median 10 minutes of session time, as a
    rule one executor and one review round, roughly $2–10 by its share of the slice's session
    time, plus the consult the generation forces (slice 146's was $4.02 with it). 10 % of the
    cost of the slices that have one, 1 % of all spend.

### 3.7 Test gaps, and the one closed finding that came back

The operator asked whether closing test gaps neglects the code base.

| entries ruled (test gaps by keyword, which finds a bit over half) | n | carded | fixed | closed |
|---|--:|--:|--:|--:|
| test gap, minor | 30 | 33 % | 7 % | 60 % |
| test gap, nit | 32 | 3 % | 3 % | 94 % |
| other Bugs and Suggestions | 760 | 21 % | 22 % | 56 % |

19. **What reaches the report is the residue**: a gap on an acceptance criterion is a blocking
    finding and is fixed in the round.
20. **No closed test gap came back.** 70 closed gaps against about 630 tracker cards and issues
    of both projects: no hit, one near miss (same file, another code path). The reading went by
    title and by the names each gap uses; a defect described by symptom alone could be missed.
21. **One closed finding did, and it was not a test gap**: KubeCoder 163 B5, a witnessed race
    graded minor whose Consequence said it corrects itself, closed in a blanket ruling on the
    operator's own reading, carded as a Major nine days later and absorbed into slice 190. The
    entry had analysed one interleaving. The table of this plan closes it too — a reader labels
    it as the entry describes it — and D7's check would not have looked. The operator's "there
    will always be bugs" covers it; no rule here claims to.

### Sources

- The label data and the brief it was made on are committed:
  `docs/research/data/close-out-labels-2026-09-29.json`,
  `docs/research/data/close-out-label-brief-2026-09-29.md`. Whose ruling an entry is comes from
  the sessions in `docs/research/data/close-out-read-2026-09-28.json`.
- The entries with their fates regenerate with `close_out_readout.py extract`, the snapshots
  with `snapshots` (the hand-over, § 6).
- The scripts behind these tables are not in the repository:
  `/work/scratch/close-out-discussion-2026-09-29/` (`focus_check.py`, `who_ruled.py`,
  `score.py`, `appended.py`, `testgaps2.py`). They are owed to `close_out_readout.py` (§ 6).
- Every share is good to a few points, as in the read: the fate classifier is a list of
  patterns, and the labels and the session coding are model judgments.

## 4. The design

### 4.1 Facts from the author, policy in the tool

- **The author labels, the tool routes.** An author says what it knows about the thing it
  reports. It is never asked what should happen to it: it does not know the operator's bar, and
  a bar written into eight registers cannot be moved.
- **The policy is one table** in `close_out.py`. A routing can always be explained from the
  labels it rests on, and a readout can hold the labels against the rulings.
- **The wrap-up changes facts, never routes.** What it finds in the code it writes as a fix, a
  corrected label or a card request; the table routes again.
- **Nothing that comes to the operator is decided by anyone else.**

### 4.2 The labels

Given by the author through `close_out.py append`, written by the tool on a line of their own,
defined in `docs/close-out.md` and nowhere else.

| label | values | |
|---|---|---|
| **kind** | `action` | only the operator can do it |
| | `decision` | the entry states a choice that is the product owner's: options to pick from, a convention to rule on |
| | `event` | something that happened to the run |
| | `defect` | the code, the configuration or the deployed system does something wrong today, however rarely |
| | `prose` | text is wrong, stale or missing — a document, a comment, help text, a message — and the behaviour is not in question |
| | `test gap` | a test is missing, pins nothing or cannot fail, and the code it would guard is right today |
| | `hardening` | right today; to be guarded against a condition that does not occur with the code as it is |
| | `cleanup` | a change without a change in behaviour |
| | `improvement` | a potential improvement: something the product could do, or do otherwise (§ 4.4) |
| **trigger** | `normal use` | shows on a path ordinary use takes |
| | `ordinary condition` | needs what ordinary operation produces now and then: a restart, a second environment, a slow dependency, an upgrade, a legitimate but particular input |
| | `fault` | needs a fault, a narrow timing window, a misconfiguration, a misuse, or several conditions together |
| | `future change` | cannot show with the code as it is |
| | `none` | there is no problem that could show |
| **impact** | `severe` | data lost or corrupted, something exposed, or a failure that cannot be recovered without repair |
| | `broken` | a wrong result, or a flow that fails or stays stuck until somebody intervenes |
| | `degraded` | it works, and somebody is told something wrong or notices it is worse: a wrong message, status or document, a fault that corrects itself, a slowdown |
| | `none` | nobody would notice; what is cosmetic is here |
| **fix** | `one edit` | the entry states the exact change, in one place |
| | `several places` | known and mechanical, in more than one place |
| | `design` | a choice with consequences is open, or the change adds behaviour — a code path, a piece of state, a process, a gate |
| **area** | `plain` · `sensitive` | sensitive: the change touches concurrency or timing, the layout of stored data, a wire contract, or authentication and secrets |
| **repo** | a name | the repository the fix lives in; the tool reads from the run's record whether the slice touched it |
| **for** | a slice, optional | the slice still to run that should take it |

`trigger`, `impact` and `fix` also take `unknown`: the author could not tell. The evidence class
(`witnessed`, `read`) and the grade stay where they are, on the Provenance line and the heading.

What the labellers of § 3.3 found unsharp, settled here:

- **A decision states its choice.** An entry that ends in "the operator's call" is what it was
  before that sentence. The replay's `question` is the decision; its `idea` is a potential
  improvement.
- **A limit the plan chose is not a defect.** An entry that proposes to lift it is a potential
  improvement; one that only records it restates the plan and is not an entry.
- **Input for a later slice is a label beside the kind**, not a kind: a defect that a later
  slice should take is still a defect. In the replay the order of precedence made such entries
  lose theirs.
- **An action or an event that describes a problem** carries that problem's trigger and impact;
  one that does not carries `none` twice.
- **A test gap, a hardening and a cleanup** carry the trigger and impact of what they would
  prevent — as a rule `future change`.
- **Prose is labelled by what following the words does**: a procedure that fails when followed
  is `broken`, a stale pointer is `none`. It has no sensitive area.
- **An entry the run already fixed** is struck by whoever fixed it (0.9.56), so it is not
  labelled at all.

### 4.3 The policy table

The first row that fits.

| | an entry that is | goes |
|--:|---|---|
| 1 | an action | to the operator |
| 2 | a decision | to the operator |
| 3 | `severe`, or graded major — whatever its trigger, however easy its fix | to the operator, as a risk |
| 4 | an event that describes no problem | to the record |
| 5 | input for a slice that exists | to that slice (D8) |
| 6 | fixable only in a repository the slice did not touch | to a card request when it shows in normal use or on an ordinary condition and has an impact; closed otherwise |
| 7 | prose; or fixed by one edit or in several known places, outside a sensitive area | to the wrap-up, to fix |
| 8 | anything else, with a trigger or an impact `unknown` | to the wrap-up, to look |
| 9 | anything else that shows in normal use or on an ordinary condition and has an impact | to the wrap-up, to fix within its bar or to ask for a card |
| 10 | anything else: it needs a fault or a future change, or has no impact | closed |

Rows 1–3 are the operator's first tier and their ruling on severity. Row 7 is their first two
bullets, rows 9 and 10 the third. Rows 5 and 6 rest on labels the replay did not have; § 3.4 is
the table without them.

The table is for what should be fixed: Bugs, and the Suggestions that are "kind of in the bug
category" — a defect, prose or a test gap entered as a Suggestion takes the same rows as one
entered as a Bug. A potential improvement takes none of them (§ 4.4).

### 4.4 Potential improvements

Not settled. The operator wants the Suggestions that are potential improvements labelled as
well, "with different attributes", and given "a different treatment" from what should be
fixed; which attributes, and where such an entry goes, is being worked out with them and is not
designed here. Until it is, this plan fixes two things only: the kind exists, so that an author
can say an entry is one, and no row of § 4.3 applies to it. What the replay did with the
entries nearest to it — it sent an idea to the operator and took a hardening and a cleanup
through rows 7 to 10 — is in § 3.4's numbers and is not a proposal; whether a hardening or a
cleanup is something that should be fixed or a potential improvement is part of the same
question.

### 4.5 How it is shown

On the entry, in words, between the Consequence and the Provenance; the route below it is
`render`'s:

```markdown
### B3 — controller: the roll's status line reports … · minor

<the body>

**Consequence:** <what is experienced, and what has to happen for it to be reached>
**Triage:** defect · shows on an ordinary condition · breaks a flow · fix needs design ·
sensitive area · in KubeCoder
**Provenance:** witnessed — code-reviewer, P3 r1
**Route:** the wrap-up — fix within its bar, or ask for a card
**Disposition:**
```

That is all there is to read besides the entries. The report has no list at its head and the
close-out card none in its body — the operator reads neither; the card's body is the report's
path and the entry counts. `close_out.py list` stays what it is, the view an agent takes before
it appends.

The tool refuses, naming the flag, so that the author corrects in one turn:

- an entry without its labels;
- an impact other than `none` over a `Consequence:` that opens with "none", and the reverse;
- a `for` that names no slice folder.

### 4.6 The wrap-up phase

**One agent, `dev:wrap-up`**, on Opus, pinned in its definition so that a session on another
model cannot move it. It is called the wrap-up, never a sweep: the run loop has its gate sweep
and the plugin the residual sweep.

**Its input** is the report as rendered, and the repositories the slice touched.

**Its bar is the residual sweep's litmus** (`plugins/dev/docs/residual-sweep.md`), which was
calibrated on the same class of work: what to change is fully decided, it is corrected in
place, it adds no behaviour, and it touches nothing on timing, stored data, wire contracts or
secrets. To that it adds: a fix whose proof needs a deploy is not its to make, and a repository
the plan holds is not its to touch.

**What it does**, entry by entry, for the entries the table sent it:

| it finds | it writes |
|---|---|
| a dated note says the run fixed it, and the commit is there | a strike naming that commit |
| the change is within the bar | the edit, the component's gate, one commit for the entry, a strike naming it |
| the label said one edit and the code says otherwise | the label corrected, with a note of what it found (`relabel`) |
| a likely problem it cannot fix within the bar | a card request: how it is reached, what the fix takes |
| a trigger or an impact the author could not tell | the label, from the code |
| a gate that goes red on its fix | the fix taken back, a note, the entry left as it was |

**What it never does**: touch an entry that comes to the operator (D5 is the one exception
asked for), file a card, push, widen a fix beyond its entry, strike what it did not fix. What
the table closes stays live and folded until the operator closes the report.

**No review round.** A review of the wrap-up's diff writes advisory findings, those are entries,
and entries go to a wrap-up: the loop has no end, and fix rounds on advisory findings are a
settled no. Its assurance is the bar, the gate, and one commit per entry — each can be read and
taken back on its own. It is what the operator's "fix inline please" gets today.

**Two callers.**

- *The close-out session (0.9.58).* `/dev:close-out` renders the report, dispatches the wrap-up
  when entries wait for it, and presents the entries that come to the operator meanwhile; the
  card requests follow when it returns. Its commits land as the skill's `fix now` lands
  today. The check of what has moved since the run stays the session's (finding 12 of the
  read).
- *The driver (0.9.59).* After the doc-writer's session and before the phase's gate sweep and
  landing, so that the driver's one landing carries both. Its commits sit on a branch of
  their own. It never fails the run: a timeout, a missing verdict, a `blocked`, or a sweep that
  is red with its commits and green without them leaves its commits out of the landing, takes
  the report back to where it stood, and is logged; the close-out session then finds the
  entries waiting. It needs a dispatch path of its own — `_spawn` ends in a ruling that bails
  the run — that still leaves the `history` row `slice_cost.py` prices a role from. The phase
  is optional per project, like the test and the doc phase.

**An entry without labels** — a report an older plugin wrote, an author that drifted — is
labelled by the wrap-up from its text before anything is routed. § 3.3 is that case, measured.

### 4.7 Card requests

A card request is an entry that comes to the operator, with what the wrap-up found under it. The
table makes one where the fix lives elsewhere (row 6), the wrap-up where a likely problem is
beyond its bar (row 9). Nothing is filed before the operator's word; "go" files them as
requested, entries that are one fix as one card.

### 4.8 The report after

```markdown
# Close-out — slice NNN <slug>

Run: <stamped by the driver>

## Summary                  the doc-writer's: the slice and what shipped

## Comes to you             actions, decisions, risks — read in full
## Card requests            read in full, with what the wrap-up found

## For the wrap-up          what waits for it; empty once it has run
## Unlabelled               entries without labels, until they have them

## Closed                   one line each — body folded; heading, Consequence, Triage and
                            Route stay in view
## Record                   the run's events that describe no problem, as headlines; then what
                            was struck — by the run, by the wrap-up, on the operator's word —
                            folded
```

Inside a section the order is the grade (major, minor, ungraded, nit, cosmetic), then the kind,
then the id. `render` writes the sections that hold something, and the Summary always. Where
a potential improvement stands in this order waits for § 4.4.

### 4.9 What stays, what goes

| | |
|---|---|
| **stays, built** | 0.9.56: whoever fixes an entry strikes it, a round that passed is not an event (R2, R3) |
| **stays, from the superseded plan** | the report ordered by what is asked of the operator; bodies folded where one line settles it; the record; one agent with two callers; the tool as the only pen; the corpus check; the five section names as what the loops' own calls take |
| **goes** | `dev:close-out-sorter`; the sorting rules as an agent's definition; `propose` and the `Proposed:` line; the Unsorted section; the second pass on the rules proposed during the discussion — the wrap-up decides with the code in hand instead of predicting a ruling |
| **goes, ruled** | the Focus lines, a written one in a report still open being dropped at its next `render`; the sheet at the report's head and in the card's body |
| **left alone** | the grade and its vocabulary; the Consequence line; "in doubt, add it"; the authors' bar |

### 4.10 The consult's rider and the appended phase — unchanged

- **The appended phase** takes work the plan owes and nothing else since 0.5.1 (§ 3.6). There
  is nothing left in it to steer to the report.
- **The completion consult's rider** — it fixes comment and formatting residue in files the
  slice's diff touched — is a small wrap-up inside the run, and it is cheap because the consult
  has just read those files. Moving it is a question for the readout of § 7, not for this
  build.

## 5. Yours to rule

**D1 — The wrap-up may fix before you have ruled.** *Default: yes.* The contract says that
reading the report is never a license to act, and the constraint of 2026-08-17 that nothing is
struck, filed or fixed before your ruling. Your proposal lifts that for the entries the table
sends to the wrap-up, and for fixing alone: what the table closes stays live until you close the
report, and no card is filed without your word. It has not been said in so many words, so it is
asked here.

**D2 — In doubt, the label is `unknown` and the wrap-up looks.** *Default: yes.* An author that
cannot tell does not guess toward you: the wrap-up has the code and a second look, a first tier
that is inflated has neither. *The other way:* in doubt, to you — nothing is missed, and the
first tier grows with every author's caution.

**D3 — The wrap-up runs after the doc phase.** *Default: yes.* It is the only place that sees
every entry. Its fixes are then gated and not verified live, which the bar allows for: a fix
that needs a deploy to prove is a card request. *The other way:* between the completion consult
and the test phase — its fixes are verified and documented, and it never sees the entries of the
test-agent and the doc-writer, 13 % of what is handed over and in the doc-writer's case the most
progressed of any author (62 %).

**D4 — The close-out session first, the driver after the replay.** *Default: as written.*
0.9.58 runs the wrap-up with you in the session, at today's risk. 0.9.59 is built once the
replay of § 7 has priced it and compared its fixes with your rulings. *The other way:* both at
once; the price is then first read from live runs.

**D5 — The wrap-up notes what it found under a risk.** *Default: yes, for risks only.* What you
ask about a risk is whether it can happen and what the fix takes (49 exchanges in the read); you
followed 35 of 41 recommendations. The note is dated and signed, changes no label, and costs one
look per risk — about one entry a report. *The other way:* it never touches what comes to you.

**D6 — The table lives in the tool.** *Default: yes.* One policy for every project; a project
switches the phase on or off, not the rows. A per-project table waits for a project that needs
one.

**D7 — A close is checked where the impact breaks a flow.** *Default: yes.* Row 10 closes on the
author's word. Where that word says `broken`, the wrap-up checks the trigger in the code before
the close stands: 0.7 entries a report in the replay, and four of the seven cards the table
lost. *The other ways:* check nothing — the price of the table is § 3.5; or check every close,
1.5 entries a report.

**D8 — Input for a slice that exists is folded by the wrap-up.** *Default: yes.* It is appended
to that slice's `slice.md` with its provenance, and the planning of that slice rules on it with
you. On your own reading you closed 8 of 18. *The other way:* they are listed for you, one line
each, and "go" folds them.

**D9 — What is severe comes to you unfixed, however easy the fix.** *Default: yes.* Your second
bullet has an obvious fix made whatever the likelihood; your ruling on severity has what is
severe come to you. Where both hold — 25 of the 561 entries handed over in the replay, 13 among
your own rulings, of which you carded 6, closed 4 and had 3 fixed — row 3 stands before row 7:
nothing severe gets a fix no reviewer reads, and the fix costs you one word. *The other way:*
the wrap-up makes the fix and the entry still comes to you, with the commit under it.

**Open, and not yet a decision with a default:** the labels and the route of a potential
improvement (§ 4.4).

## 6. The build

Prose — contract docs, agents, skills, changelog — is the session's. Code goes to one Opus
sub-agent per version, on disjoint files, briefed from contract text that exists by then and
with the verify commands of § 7; its diff is read before the commit. Versions are taken from
`origin/main` at commit time after a fetch: `origin/main` stood at 0.9.54 on 2026-09-29, with
0.9.55 and 0.9.56 local above it.

### 0.9.57 — the labels, the routing, the report's shape

- `docs/close-out.md`, `docs/close-out-template.md`: the labels and the table, each in its one
  place; the routes; the shape; who writes what. "An automated triage pass" leaves *Deliberately
  absent*.
- `tools/close_out.py`, `test_close_out.py`: `append` with the labels and the refusals;
  `relabel`; `request-card`; the table; `render` in the new shape, reading a report in either
  layout; `counts` per route; the labels of the entries the driver and the plan loop write
  themselves. `append_entry`, `live_entries` and `find_by_headline` keep taking the five
  section names.
- Every role that appends gets the rule once, by reference: one sentence in
  `agents/code-writer.md`, `code-reviewer.md`, `test-agent.md`, `doc-writer.md`,
  `plan-writer.md`, `plan-reviewer.md` and the consults' prompts, pointing at
  `docs/close-out.md`; the dispatch line carries `append`'s usage rendered from the parser, as
  the doc-writer's dispatch carries its verbs.
- The Focus lines leave `agents/doc-writer.md`, the doc phase's prompt in `tools/run_loop.py`
  with its two tests, and `skills/run-slice/SKILL.md` Job 4, where the card's body becomes the
  path and the counts.
- `skills/close-out/SKILL.md`: rewritten around the report in its reading order.
  `skills/triage/SKILL.md` § 1: what it takes from a report, by route.
- `CHANGELOG-workflow.md`, `plugin.json`, `docs/rationale/reporting.md`.

### 0.9.58 — the wrap-up, called by the close-out session

- `agents/wrap-up.md`: new, with its `description` and `model: opus`.
- `docs/close-out.md`: the wrap-up's part, and the one exception to "append only".
  `docs/agent-dispatch.md`: the role.
- `skills/close-out/SKILL.md`: when it dispatches, what it presents meanwhile.
- `README.md`, `CLAUDE.md`, `plugin.json`'s description, `docs/rationale/overview.md`: eleven
  agents.

### 0.9.59 — the driver dispatches the wrap-up

- `tools/run_loop.py`, `test_run_loop.py`: the role (model, timeout, verdict), the dispatch
  between the doc-writer's session and the landing, its branch, a stage a resume re-enters, the
  soft failure of § 4.6. `tools/preflight.py` and `docs/project-contract.md`: the switch.
- `docs/run-loop.md`, `docs/runner-state.md`, `docs/agent-dispatch.md` follow.

### Research

- `docs/research/tools/close_out_readout.py`: the cuts of § 3 as its own — whose ruling an entry
  is, the labels and the table scored, the Focus line by place, the appended phases — reading
  the committed label data, and the new layout with its `Triage:` and `Route:` lines. A research
  commit, no version.

## 7. Verification

- `kc project test` and `kc project lint` green at every commit.
- **The corpus through the new tool.** Each of the 99 hand-over snapshots in a scratch slice
  directory: labels from the committed data where the report has them, `render`, `render`
  again. Asserted: every entry id that went in comes out once, no body lost a line, the second
  render changes nothing, `counts` gives the per-kind numbers the 0.9.56 tool gives on the
  untouched snapshot.
- **The table in the tool is the table that was tested.** The committed labels, with the
  replay's vocabulary mapped onto § 4.2's (`wrong-or-lost` to `severe`, `broken-or-stuck` to
  `broken`, `misleading` to `degraded`, `question` to `decision`, `slice-input` to a `for`),
  every repository taken as the slice's own: the routes of the 234 entries are those of § 3.4,
  the 11 ideas among them left out until § 4.4 is settled.
- **The wrap-up, priced and compared — needs your go.** Five or six slices you ruled yourself,
  each in the state the run left it: the product repository at the slice's landing commit, its
  toolchains, the hand-over snapshot with the replay's labels. The wrap-up as defined runs on
  each. Read from it: what it fixed against what you had fixed, what it asked to card against
  what you carded, what it took back on a red gate, and its price a slice beside § 3.6's. That
  takes the product's toolchains, so probably an environment of that project, and the spend of
  six sessions; nothing in it touches a spec repo or pushes.
- **One report end to end**, on a copy: `AnsibleSpecs` 029 and 032 if they are still
  unprocessed — the skill opened, the entries that come to the operator presented, the
  wrap-up dispatched, a ruling executed, the file rendered. Never on the spec repo itself
  without the operator in the session.
- **The readout after ten live slices**, from the files alone: the labels the authors gave
  against your rulings, per label as in § 3.3; the share that comes to you, and whether the
  first tier grows from slice to slice; what the wrap-up fixed, asked and took back; the closes
  you pulled back; the wrap-up's price a report. The numbers to hold it against are § 3.4's.

## 8. What it costs, what can go wrong, what stays unmeasured

- **A session per slice that re-orients on the repositories.** It works on a median 5 entries a
  report, 17 at most. Its price is not known; the nearest figures are § 3.6's $2–10 for a small
  fix phase with its review, and the 20 k tokens of the text-only sort.
- **More inline fixes than you asked for** — 37 % of the entries against the quarter you had
  fixed — in code that no reviewer reads.
- **Every author writes five labels more per entry.** The facts are in its prose already; the
  refusal costs a turn when it drifts.
- **Two plugin versions on one slice.** An older `close_out.py` cannot append to a report in
  the new shape; every environment updates its marketplace copy before its next slice. A report
  an older plugin wrote is read as it is, and its entries are labelled by the wrap-up.
- **The first tier can inflate.** Nothing stops an author from calling an impact severe. The
  refusals catch the contradiction with its own Consequence line, the readout catches the
  trend.

**Unmeasured:**

- **Labels given by authors.** Every number of § 3.3 and § 3.4 is a reader's label. An author
  knows more than its entry says and has a stake a reader has not.
- **The wrap-up.** Not simulated: "to the wrap-up" is what it would attempt, not what it would
  fix or how well.
- **What the operator cannot judge.** Labels do not find it (finding 9); D7 and D5 are the
  plan's answers and neither is tested.
- **Whether the fold hides a pick.** What the table closes shows its heading, Consequence,
  labels and route, the body folded; § 8 of the read asked the same of a sheet's line.
- **The rows the replay did not have**: where the fix lives, and the slice an entry is for.

## 9. Settled rulings this passes close to

- **Fix rounds resolve blocking findings only** (0.4.2). The wrap-up is not a round: it runs
  once, no reviewer answers it, and nothing in it is relitigated. It does spend on advisory
  findings, which that ruling kept out of the loop; it does so on the operator's own proposal
  and outside the phase loop.
- **No hand-over stages, no two-stage doc phase** (2026-09-05). The wrap-up is after the doc
  phase and not part of it. It is nonetheless a fresh session that re-orients on a repository,
  which is what that measurement priced at about twice the work. This is the plan's cost risk
  and the reason the driver's half waits for the replay.
- **No Fable beyond the refinement-writer; no weaker model for a main role.** The wrap-up is
  pinned to Opus.
- **No catch-rate or reviewer-recall work.** The readout holds labels against rulings; it seeds
  nothing and measures no reviewer.
- **No turn or token caps.** The wrap-up has none; its bound is the list of entries the table
  sent it.
- **No lanes or literal-edit bundles.** The wrap-up is not a lane a slice is put on: it takes
  what the run itself reported, in the run.
- **The doc phase is auto docs only.** Unchanged; prose the wrap-up corrects is an entry's, not
  a doc requirement.
