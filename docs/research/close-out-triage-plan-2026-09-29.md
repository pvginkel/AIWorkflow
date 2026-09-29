# The close-out report, triaged at the source — plan (2026-09-29)

Companion to [close-out-read-2026-09-28.md](close-out-read-2026-09-28.md), the read, which
this plan does not restate. It came out of the operator's discussion of that read on
2026-09-29; § 2 has their words, § 3 what was computed during it. It replaces the plan of the
same day that put a text-only sorter after the run (commit `2cdf7db`) and that plan's hand-over
(`2975c85`); both were removed when this one was finished and are in the history.

**Status: built on 2026-09-29 as plugin 0.9.57, 0.9.58 and 0.9.59** (`7c32f5f`, `615074d`,
`8159144`), in one go as ruled. § 12 says what the build verified, what it decided on the way
and what it leaves as a risk for the first live slices. The operator ruled D1 to D11 (§ 5) and
gave the word: "Yes, build it in one go." They had not read this document — they took it to say
what was discussed — so § 5 lists apart what was decided in the writing; that list was named to
them when the session closed, and they ruled on two of its items. § 10 was the hand-over for
the session that built it, and stands as it was written.

**Amended the same evening, on a remark of the operator's** in a later session (§ 2, the last
of their words): they progress what fails silently far more often than what fails loudly. They
asked for no change and left its use to the session. It is in the plan as one label and one
row — an entry says whether its problem announces itself (§ 4.2, `signal`), and what fails
loudly on an ordinary condition is closed (§ 4.3 rows 8 and 10). § 3.10 has the measurement;
§ 5 lists it as W12.

**The plan in short.**

1. **The author of an entry says what it is.** Every entry carries labels: what kind of thing it
   is, what has to happen for it to show, what is then experienced, whether it then says so
   itself, what is decided about the fix, where the fix lives. Authors write these facts in
   prose already — 87 % of the entries state them — and now give them in a vocabulary the tool
   checks (§ 4.2).
2. **The policy is the operator's and lives in the tool.** A table routes every entry from its
   labels: to the operator, to the wrap-up phase, closed, or the record. No author chooses a
   disposition (§ 4.1, § 4.3).
3. **An action and a decision always come to the operator, and nothing severe is closed on a
   label's word** — in full, first in the report, their labels in words on the entry. There is
   no list to read before the entries. In the replay that is a median 2 entries of the 11 a
   report hands over (§ 3.10).
4. **A wrap-up phase takes the rest**, after the doc phase: it fixes what is decided and safe,
   asks for a card where a likely problem is more than it can fix responsibly, and leaves closed
   what the table closes. One agent, two callers — the driver at the end of the run, the
   close-out session for a report no run wrapped up (§ 4.6).
5. **A potential improvement has labels of its own**: who is better off, when that is felt,
   whether it adds, adjusts or removes. What adds something for a benefit nobody feels today is
   closed; what benefits the workflow is Fieldnotes'; a small adjustment is the wrap-up's; the
   rest comes to the operator (§ 4.4).
6. **The text-only sorter goes.** Replayed against the rulings that are the operator's own, the
   labels and the table keep 92 % of their picks and close 20 % of the entries — 96 % and 21 %
   with the improvements on their own route, a rule chosen on the sample it is scored on; the
   sorter of the plan this one replaces kept 83 % (§ 3.2, § 3.4, § 3.9). With what fails
   loudly closed it is 95 % and 22 % (§ 3.10).
7. **The record is data, the report a rendering of it.** Entries are kept in `close-out.json`
   for their whole life; `close-out.md` is written from it and never parsed for anything but
   the operator's own line (§ 4.11, D11).
8. **One build, three commits, pushed together** (D4): the store, the labels, the routing and
   the report's shape; the wrap-up agent with the close-out session as its caller; the driver
   dispatches it (§ 6). Its first test against a repository is the first live slice (§ 7).

## 1. What changed since the sorter plan

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

On the format:

> I would very much consider storing close out information in a structured format (JSON or
> YAML) until at the very end, when the close out report is written.

On Suggestions:

> I do feel there are roughly two categories: should be fixed, and potential improvement. The
> first are kind of in the bug category. Or at least, they can be handled as such. The second
> category should get a different treatment. I want them labeled also, but of course with
> different attributes.

On the decisions of § 5, which they ruled one by one; the three they did not simply take:

> D4: I don't know about this. I'm running the last planned slice as we speak. Can't we just
> build the whole thing in one go? I'm not saying you should; I'm asking why not.

> D6: Why would we want to make this optional? If we add this, the default is ON.

> D9: Why would you want to bring these to me? I meant: high severity ones with low chance of
> occurrence come to me instead of being closed. … I have no problem never knowing of an issue.

And on where they write their rulings (D11): "Both are fine. In the beginning I sent most
responses in session, but I do feel it's kind of nice to add them on the disposition lines.
It's in-context for me."

On the build, after D4's answer:

> Yes, build it in one go. Can you please finalize the plan? I will wrap up this session and not
> come back to it, so make sure everything is written down.

And on the list of what had been decided in the writing, named to them as the session closed:

> I don't read the summary.
>
> I don't need the switch.

And the same evening, in a later session, on a factor in their rulings that the plan did not
name. Their example was Ansible 029 B5, a defect graded minor, which they closed: a tool can
write a resource request above the container's limit, and the deploy's sync then fails until
somebody edits the file.

> I will far more often progress/card issues that cause silent problems, than issues that
> cause loud problems. … If this issue is hit, it will fail loudly. (I assume at deploy
> already.) So I close it. Likelihood of this occuring? I'm guessing medium to low, but not
> clearly low. So it's a real risk. But I know that when we hit this, it will be very visible.
> So I'm OK with it. If this instead would e.g. silently disable the limit … then I would have
> progressed this.
>
> I'm not asking you to make any change to the plan. But, if you feel like this clarifies
> something in the plan, i.e. really helps improving the plan, then please use it.

**Ruled by these words:**

- The Focus lines go: they are not read.
- No list at the head of the report and none in the close-out card's body: they are not read
  either. The report is its entries.
- The rulings that count are the operator's own — a session they ruled themselves, and the
  entries they named before handing over the rest. Rulings taken from a sheet do not.
- The policy of the three bullets, for Bugs and for the Suggestions that should be fixed.
- What is severe is not closed for being unlikely, whatever its subject: it comes to the
  operator in place of the close. Where the table would fix it or ask for a card, it does.
- The author labels its entry, in a form a tool can parse, and the labels are in plain view.

- The decisions of § 5 as recorded there, D4 among them: one build.
- The Summary leaves the report. The wrap-up phase has no switch.

**Not ruled:** what § 5 lists as decided in the writing — the use made of their last remark
among it (W12), which they left to the session; and the push, which is asked when the build is
done.

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

The labels of § 3.3 through the operator's policy, mechanically. Three tables were run before
the operator ruled on severity: the three bullets as stated; with impact in the rule and an
event that describes a problem routed as that problem; and with what is severe placed ahead of
the easy fix, D9's default. The table as ruled is § 3.9's.

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
    narrower; and it sent every idea to the operator as a decision — 26 of the 171 — which
    § 4.4 routes otherwise. § 3.9 has the count as ruled, with the same wide label.
13. **The wrap-up would attempt more than the operator asked for.** It gets 37 % of the entries
    to fix where the operator had a quarter fixed; of those 87 they had 41 fixed, 12 carded or
    folded and 34 closed. Part of those closes were effort, in their own words, so an entry the
    table fixes and they closed is not counted as an error. The score runs one way: what the
    table closes and they progressed.
14. **Rulings taken from a sheet agree more**, as in the read: the same table closes 21 % of
    those 215 entries and 4 % of what it closes was progressed.

### 3.5 The misses

§ 3.4's last table closes nine picks, seven cards and two inline fixes. The tables as ruled
(§ 3.9) close five, none graded above minor:

| class | entries | |
|---|--:|---|
| an event that describes a failing test run, a fault for a trigger | 2 | carded |
| a defect and a test gap that break a flow, a fault for a trigger | 2 | carded |
| a defect of slight impact, a fault for a trigger, fix needs design | 1 | fixed inline |

The three cards the first tables lost among hardening and cleanup come to the operator as
potential improvements (§ 4.4 row 5).

All four lost cards have an impact that breaks a flow. Of the 37 closes on the operator's own
rulings 12 do; over all 47 reports 24 of 67 closes, 0.5 a report. Those are the closes D7 has
the wrap-up check in the code.

The table as amended (§ 3.10) closes a sixth pick, a card: a defect that breaks a flow on an
ordinary condition, loudly, with a fix that needs design. It breaks a flow as the other four
cards do, so D7's check reads it too.

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

### 3.8 Potential improvements

The 89 entries the first pass called an idea, a hardening or a cleanup — 76 of them
Suggestions — labelled a second time, as potential improvements, by one Opus sub-agent from the
entry text. 48 are the operator's own rulings, the entries they asked advice on included: 15
carded, 6 fixed, 27 closed.

| label | value | entries | progressed | carded | fixed |
|---|---|--:|--:|--:|--:|
| change | adjusts what exists | 20 | 65 % | 50 % | 15 % |
| | removes something | 8 | 50 % | 25 % | 25 % |
| | adds something | 18 | 22 % | 17 % | 6 % |
| felt | in use, as things are | 13 | 62 % | 62 % | 0 % |
| | after a change | 25 | 40 % | 20 % | 20 % |
| | after an incident | 5 | 20 % | 20 % | 0 % |
| | not observable | 5 | 40 % | 20 % | 20 % |
| benefit | a user | 10 | 60 % | 60 % | 0 % |
| | the workflow | 6 | 50 % | 50 % | 0 % |
| | the code | 16 | 44 % | 19 % | 25 % |
| | operations | 16 | 31 % | 19 % | 12 % |
| ground | met in the run | 8 | 62 % | 38 % | 25 % |
| | left by the slice | 35 | 40 % | 29 % | 11 % |
| | read in passing | 5 | 40 % | 40 % | 0 % |

22. **The Suggestions are not random, as the operator says.** Five of the 48 were read in
    passing; the rest came out of the slice's own work. That is also why `ground` separates
    nothing — the labeller called it the least reliable of the labels — and it is not in the
    design.
23. **What adds something for a benefit nobody feels today is what the operator closes**: 13 of
    the 48, none progressed. Over all rulings 18, of which 2 were progressed, both on a sheet.
24. **An improvement is carded or closed, seldom fixed inline**: 6 of 48, none of them where a
    user is the one better off.

§ 4.4's routes against the same 48:

| route | entries | closed | fixed | carded |
|---|--:|--:|--:|--:|
| to Fieldnotes | 6 | 3 | 0 | 3 |
| to the wrap-up | 15 | 9 | 3 | 3 |
| to the operator: it prevents something severe, in place of a close | 2 | 0 | 1 | 1 |
| closed | 11 | 11 | 0 | 0 |
| to the operator | 14 | 4 | 2 | 8 |

25. **These are the numbers of a rule chosen on its own sample.** Three rules were tried on the
    48 and the one that lost no pick was kept; the two labels it rests on were named from a
    reading of the rulings before any entry was labelled. § 3.9's 96 % is an upper bound, and
    what holds of it is the readout's to say (§ 7).

### 3.9 The tables as ruled

§ 3.4's last table put what is severe before the easy fix. The operator ruled the other way
(D9): severity keeps an entry from being closed and changes nothing else. Both tables as § 4.3
and § 4.4 now have them — the 89 potential improvements by § 4.4, every other entry by § 4.3 —
against the 234 rulings of § 3.4:

| route | entries | | closed | fixed | carded | folded |
|---|--:|--:|--:|--:|--:|--:|
| to the operator: an action | 14 | 6 % | 11 | 0 | 3 | 0 |
| to the operator: a decision | 11 | 5 % | 3 | 4 | 3 | 1 |
| to the operator: severe or graded major, in place of a close | 8 | 3 % | 4 | 1 | 3 | 0 |
| to the operator: a potential improvement | 10 | 4 % | 3 | 2 | 5 | 0 |
| to the wrap-up: fix | 89 | 38 % | 32 | 40 | 16 | 1 |
| to the wrap-up: a potential improvement | 13 | 6 % | 8 | 3 | 2 | 0 |
| to the wrap-up: fix, or ask for a card | 11 | 5 % | 5 | 2 | 4 | 0 |
| to the wrap-up: look | 3 | 1 % | 1 | 0 | 2 | 0 |
| input for a later slice | 22 | 9 % | 9 | 4 | 3 | 6 |
| to Fieldnotes | 4 | 2 % | 2 | 0 | 2 | 0 |
| closed | 37 | 16 % | 32 | 1 | 4 | 0 |
| the record | 12 | 5 % | 12 | 0 | 0 | 0 |

107 of 112 picks kept (96 %), 51 of 55 cards and folds (93 %), 21 % of the entries closed. Over
everything the 47 reports handed over:

| | entries | | a report, median | max |
|---|--:|--:|--:|--:|
| comes to the operator | 124 | 22 % | 2 | 8 |
| goes to the wrap-up | 279 | 50 % | 5 | 24 |
| input for a later slice | 43 | 8 % | 0 | 8 |
| to Fieldnotes | 13 | 2 % | 0 | 2 |
| closed | 67 | 12 % | 1 | 6 |
| the record | 35 | 6 % | 0 | 4 |

26. **The ruling takes 38 entries off the operator's page** — 162 came to them with what is
    severe first, 124 as ruled — and gives the wrap-up 28 entries that are severe or graded
    major: 19 to fix, 9 to fix or ask for a card.
27. **Half of what a report hands over is the wrap-up's.** Of the 116 such entries among the
    operator's own rulings they had 45 fixed, 25 carded or folded and 46 closed.

§ 3.10 has the table with the operator's later remark in it. Its numbers take the place of
these as what the first readout is held against.

### 3.10 Loud and silent

The operator's remark of the evening (§ 2), measured. The 233 entries of the two passes that
describe a problem and are not prose — 85 defects, 58 test gaps, 25 events that describe a
problem, and the 65 potential improvements that prevent something — were labelled a third
time, by two Opus sub-agents, from the entry text alone and with the dispositions not visible,
on one question: when the problem happens, does whoever meets it know, at that moment and
without looking for it, that something went wrong? 128 are silent, 83 loud, 22 unknown (9 %);
the entry says it in so many words in 46 %. 95 are the operator's own rulings.

| | signal | entries | progressed | carded or folded | fixed |
|---|---|--:|--:|--:|--:|
| every labelled entry | silent | 57 | 51 % | 37 % | 14 % |
| | loud | 29 | 24 % | 17 % | 7 % |
| | unknown | 9 | 44 % | 33 % | 11 % |
| a defect | silent | 20 | 55 % | 40 % | 15 % |
| | loud | 16 | 25 % | 19 % | 6 % |
| a test gap, by what it would prevent | silent | 14 | 50 % | 50 % | 0 % |
| | loud | 4 | 25 % | 0 % | 25 % |
| a potential improvement, by what it would prevent | silent | 21 | 52 % | 29 % | 24 % |
| | loud | 5 | 0 % | 0 % | 0 % |
| what should be fixed, an easy fix | silent | 14 | 71 % | 64 % | 7 % |
| | loud | 3 | 67 % | 33 % | 33 % |
| what should be fixed, not an easy fix | silent | 22 | 36 % | 27 % | 9 % |
| | loud | 21 | 24 % | 19 % | 5 % |

The routes of § 3.9 where the label was given to more than a few entries, split by it:

| route of § 3.9 | signal | entries | progressed |
|---|---|--:|--:|
| to the operator: severe or graded major, in place of a close | silent | 8 | 50 % |
| to the wrap-up: fix | silent | 14 | 71 % |
| | loud | 3 | 67 % |
| to the wrap-up: fix, or ask for a card | silent | 6 | 83 % |
| | loud | 5 | 20 % |
| closed | silent | 13 | 0 % |
| | loud | 19 | 21 % |

28. **The rulings show what the operator says.** What fails silently is progressed twice as
    often as what fails loudly: 51 % against 24 %, among defects 55 % against 25 %. The rulings
    that are not their own show the same at half the level, 26 % against 11 %.
29. **The labels the plan had carry most of it.** What the table closes and is silent was
    never progressed, 0 of 13, and every pick the table loses is loud, or unknown in one case.
    What the replay calls severe is silent without exception: its wide label holds the wrong
    results, and a wrong result is what nobody is told of. A rule that keeps what is silent
    from being closed was tried: it keeps no pick more and gives the wrap-up 22 entries more.
    It is not in the design.
30. **It separates in one row**, the one that fixes or asks for a card: 83 % against 20 % on
    the operator's own rulings, and 69 % against 17 % over every ruling whoever made it (13
    silent entries, 18 loud). The operator's example belongs to this row: an ordinary
    condition, a flow that breaks, a fix that is more than one edit.
31. **An easy fix is made whatever the signal**, 71 % and 67 %. The label has its place in the
    third bullet of the policy and nowhere else.
32. **A potential improvement follows the same line**, 52 % against none of five, and needs
    no label for it: of the 15 that prevent something loud, nine are closed, Fieldnotes' or
    the wrap-up's by § 4.4's rows as they are. The six that come to the operator hold none of
    their own rulings, so the replay says nothing on them.

Three rules were run over the 234 rulings of § 3.9:

| table | picks kept | cards and folds kept | entries closed | to the wrap-up, all reports |
|---|--:|--:|--:|--:|
| as ruled (§ 3.9) | 96 % | 93 % | 21 % | 279 |
| what is silent is not closed | 96 % | 93 % | 15 % | 301 |
| what is loud on an ordinary condition is closed | 95 % | 91 % | 22 % | 260 |
| both | 95 % | 91 % | 17 % | 282 |

The third is § 4.3 as amended. By route, against what the operator did:

| route | entries | | closed | fixed | carded | folded |
|---|--:|--:|--:|--:|--:|--:|
| to the operator: an action | 14 | 6 % | 11 | 0 | 3 | 0 |
| to the operator: a decision | 11 | 5 % | 3 | 4 | 3 | 1 |
| to the operator: severe or graded major, in place of a close | 9 | 4 % | 5 | 1 | 3 | 0 |
| to the operator: a potential improvement | 10 | 4 % | 3 | 2 | 5 | 0 |
| to the wrap-up: fix | 89 | 38 % | 32 | 40 | 16 | 1 |
| to the wrap-up: a potential improvement | 13 | 6 % | 8 | 3 | 2 | 0 |
| to the wrap-up: fix, or ask for a card | 7 | 3 % | 2 | 2 | 3 | 0 |
| to the wrap-up: look | 3 | 1 % | 1 | 0 | 2 | 0 |
| input for a later slice | 22 | 9 % | 9 | 4 | 3 | 6 |
| to Fieldnotes | 4 | 2 % | 2 | 0 | 2 | 0 |
| closed | 40 | 17 % | 34 | 1 | 5 | 0 |
| the record | 12 | 5 % | 12 | 0 | 0 | 0 |

106 of 112 picks kept (95 %), 50 of 55 cards and folds (91 %), 22 % of the entries closed. Over
everything the 47 reports handed over:

| | entries | | a report, median | max |
|---|--:|--:|--:|--:|
| comes to the operator | 126 | 22 % | 2 | 8 |
| goes to the wrap-up | 260 | 46 % | 5 | 21 |
| input for a later slice | 43 | 8 % | 0 | 8 |
| to Fieldnotes | 13 | 2 % | 0 | 2 |
| closed | 84 | 15 % | 1 | 7 |
| the record | 35 | 6 % | 0 | 4 |

33. **The rule moves 19 entries, 0.4 a report**: 17 are closed, and two that are graded major
    come to the operator in place of the close. Of the 16 that anybody ruled, 13 were closed
    and 3 carded; of the operator's own four, three were closed and one carded, which is the
    pick the table now loses (§ 3.5).
34. **The rule rests on the operator's word, not on this score.** The row holds eleven of
    their own rulings; on those the rule loses one card and takes three entries from the
    wrap-up that they closed. The replay says that their rulings do not contradict them, and
    no more.
35. **Where a reader could not draw the line**, by the labellers' own account: a message that
    states something false and reads as true; an error that is plain while its cause is hidden
    or blamed on something else; output that is visibly odd without an error; a problem that
    is silent when it happens and fails loudly somewhere else a step later; an entry with two
    outcomes, one of each. § 4.2 settles them.

### Sources

- The label data and the briefs it was made on are committed:
  `docs/research/data/close-out-labels-2026-09-29.json` and
  `close-out-label-brief-2026-09-29.md` (the first pass),
  `close-out-improvement-labels-2026-09-29.json` and
  `close-out-improvement-label-brief-2026-09-29.md` (the second),
  `close-out-signal-labels-2026-09-29.json` and `close-out-signal-label-brief-2026-09-29.md`
  (the third, § 3.10). Whose ruling an entry is comes from the sessions in
  `docs/research/data/close-out-read-2026-09-28.json`.
- The entries with their fates regenerate with `close_out_readout.py extract`, the snapshots
  with `snapshots` (the hand-over, § 6).
- The cuts behind these tables are subcommands of `docs/research/tools/close_out_readout.py`:
  `focus` (§ 3.1), `who` (§ 3.2), `labels` (§ 3.3, § 3.4), `improvements` (§ 3.8), `tables`
  (§ 3.5, § 3.9), `signal` (§ 3.10), `appended` (§ 3.6), `testgaps` (§ 3.7). On the day they
  were eight ad-hoc scripts, `docs/research/tools/close_out_discussion_2026_09_29/`; the build
  took them into the tool, where they reproduce every number here, and the folder is in the
  history. Where a cut routes an entry as the plugin does, it calls the plugin's own function.
  § 3.7's check against the tracker was a sub-agent's reading and has no script.
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
| | `improvement` | nothing is wrong today: a guard against what does not occur with the code as it is, a cleanup, behaviour the product could have or have otherwise. It takes § 4.4's labels in place of trigger, impact and fix |
| **trigger** | `normal use` | shows on a path ordinary use takes |
| | `ordinary condition` | needs what ordinary operation produces now and then: a restart, a second environment, a slow dependency, an upgrade, a legitimate but particular input |
| | `fault` | needs a fault, a narrow timing window, a misconfiguration, a misuse, or several conditions together |
| | `future change` | cannot show with the code as it is |
| | `none` | there is no problem that could show |
| **impact** | `severe` | data lost or corrupted, something exposed, or a failure that cannot be recovered without repair |
| | `broken` | a wrong result, or a flow that fails or stays stuck until somebody intervenes |
| | `degraded` | it works, and somebody is told something wrong or notices it is worse: a wrong message, status or document, a fault that corrects itself, a slowdown |
| | `none` | nobody would notice; what is cosmetic is here |
| **signal** | `loud` | when it happens it says so itself: an error, a crash, a refused request or deploy, a red gate, a flow that visibly stops — whoever meets it knows that something went wrong |
| | `silent` | nothing says so: a wrong result taken for a right one, a protection that does not protect, data lost or changed without a message, a step skipped and reported done, a status that states something false and reads as true |
| **fix** | `one edit` | the entry states the exact change, in one place |
| | `several places` | known and mechanical, in more than one place |
| | `design` | a choice with consequences is open, or the change adds behaviour — a code path, a piece of state, a process, a gate |
| **area** | `plain` · `sensitive` | sensitive: the change touches concurrency or timing, the layout of stored data, a wire contract, or authentication and secrets |
| **repo** | a name | the repository the fix lives in; the tool reads from the run's record whether the slice touched it |
| **for** | a slice, optional | the slice still to run that should take it |

`trigger`, `impact`, `signal` and `fix` also take `unknown`: the author could not tell. The
evidence class (`witnessed`, `read`) and the grade stay where they are, on the Provenance line
and the heading; the grade applies to every kind, as it does today.

**An entry's id is its kind's letter and a number**: `A` action, `D` decision, `E` event, `B`
defect, `P` prose, `T` test gap, `I` improvement. The five section names the loops' own calls
pass today are taken as kinds — Outstanding actions an action, Notable events an event, Bugs a
defect, Open questions and rulings a decision, Suggestions an improvement — so the pre-run
action check and the plan loop's seeding do not change.

What the labellers of § 3.3 found unsharp, settled here:

- **A decision states its choice.** An entry that ends in "the operator's call" is what it was
  before that sentence. The replay's `question` is the decision; its `idea` is a potential
  improvement.
- **A limit the plan chose is not a defect.** An entry that proposes to lift it is a potential
  improvement; one that only records it restates the plan and is not an entry.
- **Input for a later slice is a label beside the kind**, not a kind: a defect that a later
  slice should take is still a defect. In the replay the order of precedence made such entries
  lose theirs.
- **An action or an event that describes a problem** carries that problem's trigger, impact
  and signal; one that does not carries `none` for each.
- **A test gap** carries the trigger, impact and signal of what it would prevent — as a rule
  `future change`, and the signal of the fault as it would be met in use: a gate that stays
  green is what every test gap is. The replay's `hardening` and `cleanup` are potential
  improvements: neither says that something is wrong today.
- **Prose is labelled by what following the words does**: a procedure that fails when followed
  is `broken`, a stale pointer is `none`. It has no sensitive area.
- **An entry the run already fixed** is struck by whoever fixed it (0.9.56), so it is not
  labelled at all.

And what the labellers of § 3.10 found unsharp in the signal:

- **The signal is of the moment the problem happens**, not of how bad or how likely it is. A
  failure that destroys data under a stack trace is `loud`; a harmless wrong number that
  nobody questions is `silent`.
- **An error that follows by itself from the same act is `loud`**: a configuration that loads
  and then fails the pod's creation. What shows only through what follows from it — a disk
  that fills, a certificate that was never renewed — is `silent`.
- **A message that states something false is `silent`; an error whose cause is hidden or
  blamed on something else is `loud`.** Output that is visibly odd and no more is `loud`.
- **Of two outcomes, one of each, the label is `silent`**, and an entry without an impact has
  no signal: `none`.

### 4.3 The policy table

The first row that fits.

| | an entry that is | goes |
|--:|---|---|
| 1 | an action | to the operator |
| 2 | a decision | to the operator |
| 3 | an event that describes no problem | to the record |
| 4 | input for a slice that exists | to that slice (D8) |
| 5 | fixable only in a repository the slice did not touch | to a card request when it shows and has an impact as row 8 says, or is `severe` or graded major; closed otherwise |
| 6 | prose; or fixed by one edit or in several known places, outside a sensitive area | to the wrap-up, to fix |
| 7 | anything else, with a trigger or an impact `unknown` | to the wrap-up, to look |
| 8 | anything else that has an impact and shows in normal use, or on an ordinary condition and is not `loud` | to the wrap-up, to fix within its bar or to ask for a card |
| 9 | anything else that is `severe`, or graded major | to the operator, as a risk |
| 10 | anything else: it needs a fault or a future change, it is `loud` on an ordinary condition, or it has no impact | closed |

Rows 1 and 2 are the operator's first tier. Row 6 is their first two bullets, rows 8 and 10 the
third, and row 9 their ruling on severity: it stands where the close would have been, and
nowhere else (D9). Rows 4 and 5 rest on labels the replay did not have; § 3.10 is the table
without them.

**What is loud on an ordinary condition is closed** — the operator's word of the evening
(§ 2, W12): "when we hit this, it will be very visible. So I'm OK with it." It is closed as what
is unlikely is closed, and row 9 stands behind it as behind every close. Three limits:

- **Only `loud` closes.** A signal that is `silent` or `unknown` leaves the entry in row 8.
- **Only in the third bullet.** An easy fix is made whatever its signal (row 6).
- **Not in normal use.** What fails on a path ordinary use takes is met by everybody, loud or
  not; it stays the wrap-up's.

The table is for what should be fixed: Bugs, and the Suggestions that are "kind of in the bug
category" — a defect, prose or a test gap entered as a Suggestion takes the same rows as one
entered as a Bug. A potential improvement takes § 4.4's rows in their place; rows 4 and 5
here hold for it as well.

### 4.4 Potential improvements

**Ruled (D10).** The line between the operator's two categories is whether
something is wrong today. What should be fixed — a defect, prose, a test gap — takes § 4.3,
entered as a Bug or as a Suggestion. A potential improvement says that something could be
better, safer or simpler, and is labelled by what it would bring and what it would take:

| label | values | |
|---|---|---|
| **benefit** | `user` | somebody using the product is better off: what they see, can do, or have to do by hand |
| | `operations` | whoever deploys, runs, upgrades or recovers the system |
| | `workflow` | the agents that build slices, their suites and gates, CI, the tools they run |
| | `code` | whoever maintains the code or the documentation |
| **felt** | `in use` | as things are today, each time or on ordinary occasions |
| | `after a change` | only once somebody changes something, or something outside changes |
| | `after an incident` | only when something goes wrong first |
| | `not observable` | nobody would notice the difference |
| **change** | `remove` | it takes something away: code, a duplicate, a step |
| | `adjust` | it changes what exists, in place |
| | `add` | it adds something: behaviour, a check, a gate, an alarm, state, a process, a document |
| **size** | `one edit` · `several places` · `design` | as § 4.2's fix |
| | `investigate` | something is to be looked into before anything changes |
| **product call** | `yes` · `no` | it changes what a user of the product sees or can do |
| **prevents** | `severe` · `broken` · `degraded` · `nothing` | the worst it would prevent, on § 4.2's scale of impact |

`area`, `repo` and `for` are § 4.2's. `benefit`, `felt`, `change`, `size` and `prevents` take
`unknown`.

Its route, the first row that fits:

| | a potential improvement that | goes |
|--:|---|---|
| 1 | benefits the workflow | to Fieldnotes, as an `idea` — it is not an entry |
| 2 | adjusts or removes, in one edit or in several known places, and is no product call | to the wrap-up, within its bar |
| 3 | adds something, for a benefit that is not felt in use, and prevents something severe | to the operator, as a risk |
| 4 | adds something, for a benefit that is not felt in use | closed |
| 5 | is anything else — a product call, a change that needs design or a look first, an addition felt in use | to the operator |

- **Row 1 is the line the contract draws already**: the report is about the work, Fieldnotes
  about working. An improvement to the workflow is posted there by its author and reaches the
  operator curated across projects; the tool refuses it as an entry and says where it goes.
- **Row 2 is the first tier of the operator's policy**, for what is not a defect: a small known
  change is made because it costs less than deciding about it. § 4.6's bar holds, and rows 4 and
  5 of § 4.3 stand before it — input for a slice that exists, a fix that lives elsewhere.
- **Row 4 is the operator's "I can think up suggestions till the cows come home"** as a rule
  the tool can apply: a gate, an alarm or a check for an event that may never come. In the
  replay it closes 11 of their 48 rulings and none they progressed (§ 3.8). Row 3 is D9 for
  this table: severity stands where the close would have been.
- **Where the entry came from is not a label.** Nearly every Suggestion comes out of the slice's
  own work (§ 3.8), so the label would say the same of all of them.
- **Nor is the signal of what it would prevent.** The rulings follow it here as well, and the
  rows as they are take what prevents something loud; the label would route nothing
  (finding 32).

### 4.5 How it is shown

On the entry, in words, between the Consequence and the Provenance; the route below it is
`render`'s:

```markdown
### B3 — controller: the roll's status line reports … · minor

<the body>

**Consequence:** <what is experienced, and what has to happen for it to be reached>
**Triage:** defect · shows on an ordinary condition · breaks a flow · silent · fix needs
design · sensitive area · in KubeCoder
**Provenance:** witnessed — code-reviewer, P3 r1
**Route:** the wrap-up — fix within its bar, or ask for a card
**Disposition:**
```

A potential improvement shows its own labels the same way:

```markdown
**Triage:** improvement · a user is better off · felt in use · adjusts what exists · fix needs
design · a product call · in KubeCoder
**Route:** to you
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
| a trigger, an impact or a signal the author could not tell | the label, from the code |
| a close on an entry that breaks a flow (D7) | the label the close rests on — its trigger, or its signal — checked in the code, and corrected where the code says otherwise |
| a gate that goes red on its fix | the fix taken back, a note, the entry left as it was |

**What it never does**: touch an entry that comes to the operator (D5 is the one exception
asked for), file a card, push, widen a fix beyond its entry, strike what it did not fix. What
the table closes stays live and folded until the operator closes the report.

**No review round.** A review of the wrap-up's diff writes advisory findings, those are entries,
and entries go to a wrap-up: the loop has no end, and fix rounds on advisory findings are a
settled no. Its assurance is the bar, the gate, and one commit per entry — each can be read and
taken back on its own. It is what the operator's "fix inline please" gets today.

**Two callers.**

- *The close-out session.* For a report no run wrapped up: a run that stopped before its end, a
  wrap-up that failed, a report an older plugin wrote. `/dev:close-out`
  renders the report, dispatches the wrap-up when entries wait for it, and presents the entries
  that come to the operator meanwhile; the card requests follow when it returns. Its commits
  land as the skill's `fix now` lands today. The check of what has moved since the run stays
  the session's (finding 12 of the read).
- *The driver.* After the doc-writer's session and before the phase's gate sweep and
  landing, so that the driver's one landing carries both. Its commits sit on a branch of
  their own. It never fails the run: a timeout, a missing verdict, a `blocked`, or a sweep that
  is red with its commits and green without them leaves its commits out of the landing, takes
  the report back to where it stood, and is logged; the close-out session then finds the
  entries waiting. It needs a dispatch path of its own — `_spawn` ends in a ruling that bails
  the run — that still leaves the `history` row `slice_cost.py` prices a role from. The phase
  is on in every project and has no switch (D6).

**An entry without labels** — a report an older plugin wrote, an author that drifted — is
labelled by the wrap-up from its text before anything is routed. § 3.3 is that case, measured.

### 4.7 Card requests

A card request is an entry that comes to the operator, with what the wrap-up found under it. The
table makes one where the fix lives elsewhere (row 5), the wrap-up where a likely problem is
beyond its bar (row 8). Nothing is filed before the operator's word; "go" files them as
requested, entries that are one fix as one card.

### 4.8 The report after

```markdown
# Close-out — slice NNN <slug>

Run: <stamped by the driver>

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
then the id. `render` writes the sections that hold something. A potential improvement stands
where its route puts it, after what should be fixed of the same grade.

**The Summary leaves with the Focus lines** — "I don't read the summary". The doc-writer
writes neither; the run header, which the driver stamps from `state.json`, stays as the one
line above the entries.

### 4.9 What stays, what goes

| | |
|---|---|
| **stays, built** | 0.9.56: whoever fixes an entry strikes it, a round that passed is not an event (R2, R3) |
| **stays, from the sorter plan** | the report ordered by what is asked of the operator; bodies folded where one line settles it; the record; one agent with two callers; the tool as the only pen; the corpus check; the five section names as what the loops' own calls take |
| **goes** | `dev:close-out-sorter`; the sorting rules as an agent's definition; `propose` and the `Proposed:` line; the Unsorted section; the second pass on the rules proposed during the discussion — the wrap-up decides with the code in hand instead of predicting a ruling |
| **goes, ruled** | the Focus lines; the Summary; the sheet at the report's head and in the card's body |
| **left alone** | the grade and its vocabulary; the Consequence line; "in doubt, add it"; the authors' bar |

### 4.10 The consult's rider and the appended phase — unchanged

- **The appended phase** takes work the plan owes and nothing else since 0.5.1 (§ 3.6). There
  is nothing left in it to steer to the report.
- **The completion consult's rider** — it fixes comment and formatting residue in files the
  slice's diff touched — is a small wrap-up inside the run, and it is cheap because the consult
  has just read those files. Moving it is a question for the readout of § 7, not for this
  build.

### 4.11 The store

**The operator's suggestion, ruled (D11).** The labels make an entry a record with a dozen
fields; the route is computed from them; the wrap-up corrects them. Kept in Markdown, each of
those is a line the tool writes and then has to find and parse again.

- **`close-out.json`, in the slice folder, is the record** — from the first append of the plan
  loop to the operator's last ruling. `close-out.md` is `render`'s output: written when the run
  stops for any reason, when it completes, after the wrap-up, and after a ruling was executed.
  Its head says that it is generated.
- **JSON, not YAML.** Plugin code is stdlib-only; Python's standard library reads and writes
  JSON and has no YAML. Nobody reads the store raw: an agent reads `list`, the operator the
  report.
- **What an entry holds**: id, kind, grade, headline, body, consequence, evidence class and
  author, labels, dated notes, a strike with its reason and commit, what the wrap-up did, the
  operator's words and what was done on them. The body is kept as lines, so that a diff of the
  store reads like a diff of text. The run header stays `state.json`'s.
- **The route is not stored.** `render` computes it from the labels, so a changed table routes
  an open report again at its next render, and a closed one can be read under any table.
- **Nothing changes for an author.** `append`, `note`, `strike` and `list` keep their
  arguments, and the three functions the loops import keep theirs.
- **The operator's line is the one thing read back** from the rendered file, by entry id, if
  they write there (D11); everything else in `close-out.md` is overwritten by the next render.

What it removes: the tool's parsing of its own report — sections, fences, comments, headings
out of shape, folds — which is about half of its 920 lines; `render` reading a report in
either layout, and having to be idempotent; and the pattern classifier the read needed to tell
an entry's fate from the words on it (88 % agreement, § 1 of the read). A ruling is data from
here on, which is what the readout of § 7 is made of.

What it costs: the 99 reports that exist stay Markdown and keep their reader in the research
tool; a report in flight at the upgrade is imported once, by the parser the tool has today; and
two files can disagree when somebody edits the rendered one by hand.

## 5. The decisions, as ruled

Put to the operator on 2026-09-29 with a default each; ruled the same day.

| | decision | ruling |
|---|---|---|
| D1 | the wrap-up may fix before the operator has ruled | **yes** — "that was happening already, and that's fine" |
| D2 | in doubt the label is `unknown`, and the wrap-up looks | **yes** |
| D3 | the wrap-up runs after the doc phase | **yes** |
| D4 | the close-out session first, the driver after a priced replay | **no: one build** — "Yes, build it in one go" |
| D5 | the wrap-up notes what it found under a risk that comes to the operator | **yes** |
| D6 | the table lives in the tool, one policy for every project | **yes, and the phase is on, without a switch**: "If we add this, the default is ON", "I don't need the switch" |
| D7 | before a close stands on an entry that breaks a flow, the wrap-up checks its trigger in the code | **yes**, on the recommendation |
| D8 | input for a slice that exists is folded into that slice by the wrap-up | **yes** |
| D9 | what is severe comes to the operator unfixed, however easy the fix | **no** — below |
| D10 | a potential improvement is labelled and routed as § 4.4 says | **yes** |
| D11 | the record is `close-out.json` for the entry's whole life, the report rendered from it | **yes**; rulings in the session and on the `Disposition:` lines, both |

**D1** lifts, for the entries the table sends to the wrap-up and for fixing alone, the
constraint of 2026-08-17 and the contract's "reading the report is never a license to act".
What the table closes stays live until the operator closes the report, and no card is filed
without their word.

**D9, as ruled.** The default had row 3 of the first table bring everything severe to the
operator. They meant less: what is severe and unlikely comes to them *instead of being
closed*; they have "no problem never knowing of an issue". So severity stands where the close
would have been and nowhere else (§ 4.3 row 9, § 4.4 row 3): a severe defect with an obvious
fix is fixed by the wrap-up, one that is likely and beyond its bar becomes a card request. The
default's reason was the fix, not the knowing — a fix no reviewer reads weighs most where the
harm is worst. The wrap-up's bar answers that: it touches nothing on timing, stored data, wire
contracts or secrets, which is where most of what is severe lives, and those entries reach the
operator as card requests.

**D7** is the one place where the wrap-up doubts a label that closes an entry: 0.5 entries a
report in the replay, and all four cards the tables as ruled lose (§ 3.5). With W12 a close
can rest on the signal in place of the trigger, and the check is of the label the close rests
on: a problem that is silent and was labelled `loud` is the one mislabel that goes against
what the operator said. That makes it 0.8 entries a report — 36 of the 84 closes break a
flow — and all five cards the table as amended loses.

**D11.** `close_out.py rule` records what the operator says in the session; before the
session executes anything it reads the `Disposition:` lines of `close-out.md` back by entry id.
Nothing else changed in that file survives a render.

**D4, as ruled: one build.** The operator asked why not, with the last planned slice running
as they asked. The staging had three reasons: the wrap-up's price is not measured; its fixes
land unattended where the close-out session has the operator present; and the driver is the
largest and riskiest code of the build. What weighed against them:

- **Nothing is in flight.** With no slice planned after the one that ran, no slice meets two
  plugin versions and no open report has to be imported. That window closes with the next
  `/dev:plan-slice`: the build ships before it, or the first slice planned waits for it.
- **The driver's wrap-up cannot fail a run** (§ 4.6), and its work is one commit per entry.
- **Live slices price it for nothing.** `slice_cost.py` prices the role from the first run; a
  replay costs an environment of the product and six sessions to learn the same.
- **The close-out session as the only caller is a wait** at the start of every close-out.
- **Two builds cost more than one**: the first would ship a report with a section for a
  wrap-up that nothing runs.

So the priced replay is not run. In its place: a look at the first live slice before the second
runs, and the readout after five (§ 7).

### Decided in the writing

The operator ruled on what was discussed and did not read this document. These were settled by
the session that wrote it, each as its best reading of what they had said. The list was named
to them in a few lines as the session closed. They ruled on W1 and W2 and raised nothing on the
rest; W3 to W11 stand as decided, not as ruled, and the building session changes one on their
word without reopening the others. W12 came after, in the session of their last remark, and
was named to them there as it was written in; it stands as the others do.

| | decided | because |
|---|---|---|
| W1 | the Summary leaves the report with the Focus lines (§ 4.8) | **ruled: yes** — "I don't read the summary" |
| W2 | the phase has an off switch in `.aiworkflowrc`, on by default | **ruled: no** — "I don't need the switch"; none is built |
| W3 | the words of every label and their definitions (§ 4.2, § 4.4); `severe` as lost or corrupted data, an exposure, or a failure that cannot be recovered without repair | the labels were discussed as a set and by example, not word by word |
| W4 | no reviewer reads what the wrap-up fixes; its assurance is the bar, the gate, one commit per entry (§ 4.6) | said in the discussion as the guard on unreviewed fixes and not objected to |
| W5 | what the table closes is not struck: it stays in the report, folded, until the operator closes the report (§ 4.6, § 4.8) | D1 lifts the constraint of 2026-08-17 for fixing alone |
| W6 | a card request is filed on the operator's word, never by the wrap-up (§ 4.7) | the same; their words were "request to card" |
| W7 | a fix that lives in a repository the slice did not touch is a card request or closed, never the wrap-up's (§ 4.3 row 5) | the wrap-up has branches and gates only where the slice ran |
| W8 | an improvement of the workflow is refused as an entry and goes to Fieldnotes (§ 4.4 row 1) | inside D10, which they ruled yes; stated here because it changes what authors may enter |
| W9 | the tool refuses an entry without labels, and one that contradicts its own Consequence line (§ 4.5) | "it's very important that the labels are decided right" |
| W10 | an entry's id is its kind's letter (§ 4.2) | the five sections go, and an id has to say what it names |
| W11 | the first readout comes after five live slices, with a look at the first (§ 7) | it stands in for the replay D4 drops |
| W12 | an entry says whether its problem is `loud` or `silent`; what is loud on an ordinary condition is closed; D7's check reads the signal where a close rests on it (§ 4.2, § 4.3 rows 8 and 10, § 3.10) | the operator's remark on what fails loudly (§ 2). They asked for no change and left its use to the session: "if you feel like this … really helps improving the plan, then please use it" |

## 6. The build

**One build, pushed together** (D4): three commits with a version each, in the order below,
and a research commit. Prose — contract docs, agents, skills, changelog — is the session's.
Code goes to one Opus sub-agent per commit, on disjoint files, briefed from contract text that
exists by then and with the verify commands of § 7; its diff is read before the commit.
Versions are taken from `origin/main` at commit time after a fetch: `origin/main` stood at
0.9.56 on 2026-09-29, which makes these 0.9.57, 0.9.58 and 0.9.59 unless something was pushed
in between. § 10 has the order of work.

### 0.9.57 — the store, the labels, the routing, the report's shape

- `docs/close-out.md`, `docs/close-out-template.md`: the store; the labels and the two tables,
  each in its one place; the routes; the shape; who writes what. "An automated triage pass"
  leaves *Deliberately absent*.
- `tools/close_out.py`, `test_close_out.py`: the store (§ 4.11) — `close-out.json` read and
  written, `import` for a report in Markdown, `rule` for the operator's words and the reading
  back of a `Disposition:` line by id; `append` with the labels of both kinds and the
  refusals, the one for an improvement of the workflow among them; `relabel`; `request-card`;
  the two tables; `render` in the new shape, from the store; `counts` per route; the labels of
  the entries the driver and the plan loop write themselves. `append_entry`, `live_entries` and
  `find_by_headline` keep taking the five section names (§ 4.2).
- Every role that appends gets the rule once, by reference: one sentence in
  `agents/code-writer.md`, `code-reviewer.md`, `test-agent.md`, `doc-writer.md`,
  `plan-writer.md`, `plan-reviewer.md` and the consults' prompts, pointing at
  `docs/close-out.md`; the dispatch line carries `append`'s usage rendered from the parser, as
  the doc-writer's dispatch carries its verbs.
- The Focus lines and the Summary leave `agents/doc-writer.md`, the doc phase's prompt in
  `tools/run_loop.py` with its tests, and `skills/run-slice/SKILL.md` Job 4, where the card's
  body becomes the path and the counts.
- `skills/close-out/SKILL.md`: rewritten around the report in its reading order, the two ways
  the operator rules (D11), and the closing of the report. `skills/triage/SKILL.md` § 1: what
  it takes from a report, by route.
- `CHANGELOG-workflow.md`, `plugin.json`, `docs/rationale/reporting.md`.

### 0.9.58 — the wrap-up, called by the close-out session

- `agents/wrap-up.md`: new, with its `description` — without one it is not registered — and
  `model: opus`.
- `docs/close-out.md`: the wrap-up's part, and the one exception to "append only".
  `docs/agent-dispatch.md`: the role.
- `skills/close-out/SKILL.md`: when it dispatches, what it presents meanwhile.
- `README.md`, `CLAUDE.md`, `plugin.json`'s description, `docs/rationale/overview.md`: eleven
  agents.

### 0.9.59 — the driver dispatches the wrap-up

- `tools/run_loop.py`, `test_run_loop.py`: the role (model, timeout, verdict), the dispatch
  between the doc-writer's session and the landing, its branch, a stage a resume re-enters, the
  soft failure of § 4.6.
- `docs/run-loop.md`, `docs/runner-state.md`, `docs/agent-dispatch.md` follow.

### Research

- `docs/research/tools/close_out_readout.py`: the cuts of § 3 as its own — whose ruling an entry
  is, the labels and the tables scored, the Focus line by place, the appended phases — reading
  the committed label data, and a report's store beside the Markdown of the 99 that exist. The
  scripts of `docs/research/tools/close_out_discussion_2026_09_29/` are what it takes them
  from; that folder is removed in the same commit. A research commit, no version.

## 7. Verification

- `kc project test` and `kc project lint` green at every commit.
- **The corpus through the new tool.** Each of the 99 hand-over snapshots in a scratch slice
  directory: `import`, labels from the committed data where the report has them, `render`.
  Asserted: every entry id that went in is in the store and in the report once, no body lost a
  line, `counts` gives the per-kind numbers the 0.9.56 tool gives on the untouched snapshot.
  The snapshots include reports from before the entry shape held (slice 146 has headings
  without ids) and entries that quote `## Bugs` inside a fence.
- **The tables in the tool are the tables that were tested.** The committed labels, with the
  replay's vocabulary mapped onto § 4.2's and § 4.4's (`wrong-or-lost` to `severe`,
  `broken-or-stuck` to `broken`, `misleading` to `degraded`, `question` to `decision`,
  `slice-input` to a `for`, `every-use` and `some-uses` to `in use`), every repository taken as
  the slice's own, the 89 potential improvements with the labels of the second pass, the
  signal of the third where an entry has one and `unknown` where it has none: the routes of
  the 234 entries are those of § 3.10.
- **One report end to end**, on a copy: `AnsibleSpecs` 029 and 032 if they are still
  unprocessed — the skill opened, the entries that come to the operator presented, a ruling
  given in the session and one written on a `Disposition:` line, both executed, the file
  rendered. Never on the spec repo itself without the operator in the session.
- **What nothing exercises before it ships: the wrap-up against a repository.** The suites
  fake every session, and the building environment holds no product repository with its
  toolchains. Its first run is the first live slice.
- **A look at the first live slice, before the second runs**: the wrap-up's commits, what it
  asked to card, what it took back on a red gate, what it left, its price from `slice_cost.py`.
  The phase has no switch: if that look goes wrong, the remedy is a fix, or 0.9.59 reverted,
  pushed before the next slice runs.
- **The readout after five live slices**, from the stores alone: the labels the authors gave
  against the operator's rulings, per label as in § 3.3, § 3.8 and § 3.10; the share that
  comes to the operator, and whether the first tier grows from slice to slice; what the wrap-up
  fixed, asked and took back; the closes the operator pulled back, those that rest on the
  signal apart; the wrap-up's price a report. The numbers to hold it against are § 3.10's.

## 8. What it costs, what can go wrong, what stays unmeasured

- **A session per slice that re-orients on the repositories.** It works on a median 5 entries a
  report, 24 at most. Its price is not known; the nearest figures are § 3.6's $2–10 for a small
  fix phase with its review, and the 20 k tokens of the text-only sort.
- **More inline fixes than you asked for** — close to half of the entries go to the wrap-up,
  where you had a quarter fixed — in code that no reviewer reads, what is severe included
  (finding 26).
- **Every author writes six labels more per entry.** The facts are in its prose already — the
  signal in a little under half of the entries, the others in 87 % — and the refusal costs a
  turn when it drifts.
- **A silent problem labelled `loud` is closed unseen.** D7's check reads the closes that
  break a flow; one that degrades shows its labels on a folded line and nothing more.
- **Two plugin versions on one slice.** An older `close_out.py` knows no store; every
  environment updates its marketplace copy before its next slice is planned. A report an older
  plugin wrote is imported once, and its entries are labelled by the wrap-up.
- **It ships without having run.** The wrap-up's first run against a repository is a live
  slice (§ 7).
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
- **The route of a potential improvement out of sample.** § 4.4's rows were fitted to 48
  rulings (finding 25).
- **The signal in the table.** The row it changes holds eleven of the operator's own rulings;
  the rule is their word, which the replay does not contradict (finding 34). And the signal as
  an author gives it: a reader could not tell in 9 %.

## 9. Settled rulings this passes close to

- **Fix rounds resolve blocking findings only** (0.4.2). The wrap-up is not a round: it runs
  once, no reviewer answers it, and nothing in it is relitigated. It does spend on advisory
  findings, which that ruling kept out of the loop; it does so on the operator's own proposal
  and outside the phase loop.
- **No hand-over stages, no two-stage doc phase** (2026-09-05). The wrap-up is after the doc
  phase and not part of it. It is nonetheless a fresh session that re-orients on a repository,
  which is what that measurement priced at about twice the work. This is the plan's cost
  risk; the operator ruled one build knowing it (D4), and the first slices price it.
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

## 10. Hand-over — for the session that builds it

### 10.1 Where it stands

| commit | what | pushed |
|---|---|---|
| `52e7f95` | the read, its tool and its data | yes |
| `5f3be47` | 0.9.55, another session's (`/dev:close-out` leaves the slice card alone) | yes |
| `2cdf7db`, `2975c85` | the sorter plan and its hand-over — replaced by this document, removed | yes |
| `3d3c4a0` | **0.9.56** — whoever fixes an entry strikes it; a round that passed is not an event | yes |
| `b36ed3c` … `ccfcf72` | the label data of both passes, this plan, the scripts | yes |
| the commit after `ccfcf72` | the amendment: the signal's label data and script, § 3.10, W12 | no |

`origin/main` stood at `ccfcf72` on 2026-09-29 at 22:00, 0.9.56 and this plan as it was before
the amendment with it. Fetch before trusting that: the operator pushes from the pod between
sessions.

**The word to build is given** ("Yes, build it in one go"). **The word to push is not**: it is
asked when the three commits and the research commit are done, and asked again for every push.
Nothing reaches a run before the push and a marketplace update in every environment.

**The operator ended the session that wrote this and will not return to it.** They ruled on
what was discussed and did not read this document; what was decided in the writing was named
to them and is § 5's list. Open the building session by saying in a few lines what will be
built. Do not ask them to read the plan, and do not put W3 to W11 to them again.

### 10.2 The order of work

1. `git fetch origin`; the versions from `origin/main` and the local commits above it.
2. The contract first: `docs/close-out.md` and `docs/close-out-template.md` — the store, the
   labels with their definitions, the two tables, the shape, who writes what. The tool's brief
   quotes them.
3. One Opus sub-agent for `tools/close_out.py` and `test_close_out.py`, with the corpus check
   and the table check of § 7 among its verify commands. Read its diff.
4. The one sentence for every role that appends; the Focus lines and the Summary out of
   `agents/doc-writer.md`; the code half — the doc phase's prompt, its tests, the dispatch
   line — to the sub-agent.
5. `skills/close-out/SKILL.md`, `skills/run-slice/SKILL.md` Job 4, `skills/triage/SKILL.md`
   § 1. Changelog, `plugin.json`, `docs/rationale/reporting.md`. Commit as 0.9.57.
6. `agents/wrap-up.md`, the wrap-up's part of `docs/close-out.md`, `docs/agent-dispatch.md`,
   the skill's dispatch; the agent count in `README.md`, `CLAUDE.md`, `plugin.json`'s
   description and `docs/rationale/overview.md`. Commit as 0.9.58.
7. The driver: `docs/run-loop.md`, `docs/runner-state.md`, `docs/agent-dispatch.md` and the
   brief together, then the sub-agent on `run_loop.py` and `test_run_loop.py`. Commit as
   0.9.59.
8. The research commit: the scripts into `close_out_readout.py`, their folder removed.
9. One report end to end on a copy (§ 7). Then ask for the push.
10. After the push: the marketplace copy updated in every environment before a slice is
    planned; the look at the first live slice; the readout after five.

### 10.3 Settled for the build, beyond § 4

- **The loops' own entries carry labels the tool gives them.** The driver's Notable events
  (a refuted finding, a stop of the run, a driver ruling taking effect) are events that describe
  no problem unless their text says otherwise; the plan loop's seeded Outstanding actions are
  actions. Neither loop passes labels of its own choosing.
- **The record's rule is a label now.** Under the sorter plan an event went to the record when
  its Consequence opened with "none"; here it goes there when its trigger and impact are
  `none` (§ 4.3 row 3), and the refusal of § 4.5 keeps the Consequence line and the labels from
  disagreeing.
- **The fold is `render`'s and nothing else's.** With the store there is no fold to take off or
  put back: a closed entry is rendered with its body folded, an entry that comes to the
  operator in full.
- **A note added by anyone lands in the store**, dated and signed, and is rendered with its
  entry.
- **The wrap-up's definition** needs a `description` — without one the agent is silently not
  registered — and `model: opus`: dispatched from a close-out session that runs on another
  model it must not inherit it, and "no Fable for any role beyond the refinement-writer" is a
  settled ruling.
- **The driver's dispatch must not go through `_spawn` as it is.** `_spawn` ends in
  `_rule_on_round`, which bails the run on a protocol failure. The wrap-up is never a reason
  to stop a run: it needs a path that logs and goes on, and still leaves the `history` row
  `slice_cost.py` prices a role from.
- **Tests the Focus lines and the Summary turn over.** `test_run_loop.py`
  `test_doc_phase_prompt_states_diff_files_digest_verbs_and_doc` asserts the Focus sentence of
  the prompt, and a test near line 1539 that the report is rendered before the doc phase — keep
  that render, a run that stalls in the doc phase then leaves a rendered report.
  `test_close_out.py` asserts section preambles with their Focus placeholders around lines 742
  and 785.
- **Not decided, and not worth a question to the operator**: the names of the wrap-up's verdict
  outcomes; the wording of the line `render` puts on a folded entry; the file name of the
  store if `close-out.json` collides with anything.

### 10.4 Where the code is

Line numbers are of 0.9.56 and say where to look. Most of `close_out.py` below line 500 is the
parser the store replaces; it stays as `import`'s reader.

| what | where |
|---|---|
| kinds, severities, the fold constants, the entry regexes | `tools/close_out.py` 103–145 |
| what every dispatch says about the report (`DISPATCH_LINE`) | `close_out.py` 103 |
| `append_entry`; `entry_counts`, `counts_line` | `close_out.py` 304; 347, 370 |
| blocks, `find_by_headline`, `live_entries`, `_find_entry` | `close_out.py` 391–495 |
| `add_note`, `strike_entry`, `list_view` | `close_out.py` 532, 565, 609 |
| `_fold`, `_render_section`, `render_report` | `close_out.py` 642–702 |
| the CLI and `verb_usage` | `close_out.py` 807–882 |
| role tables: `MODELS`, `REQUIRED_AGENTS`, `TIMEOUTS`, `VERDICTS` | `tools/run_loop.py` 127–157, 366 |
| `BAIL_STAGES`; the pre-run action check | `run_loop.py` 204; 511 |
| the completion consult's and the doc phase's prompts | `run_loop.py` 2100, 2223 |
| `_spawn`, `_dispatch_rounds` | `run_loop.py` 3383, 3413 |
| the doc phase: render, then dispatch | `run_loop.py` 5288–5320 |
| `_run`: the stage ladder, where a resume re-enters, the end of the run | `run_loop.py` 5737–5833 |
| `_render_report`, `_stamp_report`, `_summary` | `run_loop.py` 5905, 5914, 6011 |
| the plan loop's seeding of Outstanding actions | `tools/plan_loop.py` 135, 832 |
| the card's body | `skills/run-slice/SKILL.md` Job 4, step 4 |
| what triage takes from a report | `skills/triage/SKILL.md` § 1 |
| the residual sweep's litmus, the wrap-up's bar | `docs/residual-sweep.md` |
| `run_phase` and its values | `docs/runner-state.md` |

Every file that names the Focus lines or the Summary:
`grep -rn "Focus\|Summary" plugins/dev --include=*.md --include=*.py`.

### 10.5 The data, and how to make the scratch data again

Committed: the read and its data (`docs/research/data/close-out-read-2026-09-28.json`, the
sorts and the session coding as ids and buckets; `close-out-sort-brief-2026-09-28.md`), the
label data of the three passes with their briefs (§ 3, Sources), the scripts.

Not committed, and gone when the pod's `/tmp` goes: the entries with their text
(`/tmp/close-out-entries.json`) and the 99 reports as handed over (`/tmp/co/snapshots/`). They
hold entry text from the spec repos and stay out of this repository. To make them again:

```bash
git clone https://github.com/pvginkel/KubeCoderSpecs /work/scratch/KubeCoderSpecs
git clone https://github.com/pvginkel/AnsibleSpecs   /work/scratch/AnsibleSpecs
cd /work/AIWorkflow
python3 docs/research/tools/close_out_readout.py extract \
    /work/scratch/KubeCoderSpecs /work/scratch/AnsibleSpecs -o /tmp/close-out-entries.json
python3 docs/research/tools/close_out_readout.py snapshots -o /tmp/co/snapshots
python3 docs/research/tools/close_out_readout.py tables          # § 3.9, § 3.5
python3 docs/research/tools/close_out_readout.py signal          # § 3.10
python3 docs/research/tools/close_out_readout.py table-check     # the plugin's tables, held to § 3.10
python3 docs/research/tools/close_out_readout.py corpus-check /tmp/co/snapshots
```

The read and the labels were made at `KubeCoderSpecs` `9a3c102a` and `AnsibleSpecs` `c90d65c`.
On later heads the operator has ruled more reports and the shares move by a little; check those
commits out to get the numbers exactly. Every cut reads the committed labels; the labellers'
own files under `/tmp/co/` held nothing the committed data does not.

### 10.6 Rules of the house that bite here

- **No push without the operator's word**, asked again each time.
- **The version comes from `origin/main` after a fetch**, plus the local commits above it.
- **Prose is the session's own; code goes to one Opus sub-agent** on disjoint files, briefed
  with the files and the verify commands, its diff read before the commit. Have it assert on
  what the tool renders, not on what the brief says the tool renders.
- **State every claim once.** The labels, their definitions and the two tables live in
  `docs/close-out.md`; an agent's definition points there, the wrap-up's says what it does
  with a route, not how a route is reached.
- **This repository is public.** No hostnames, no tracker URLs, no entry text from the spec
  repos. Eleven of the 99 reports name hosts.
- **Plugin code is stdlib-only** — which is why the store is JSON; the research tools need not
  be.
- **What runs is the installed copy.** Nothing here reaches a run before a push and a
  marketplace update.
- **The settled rulings of § 9.**

## 11. Not part of the plan — a follow-up idea: the tracker as the operator's queue

**This section is not part of the plan, and nothing in it is to be built.** It records an idea
from a later discussion so that it is not lost. It is not ruled. The build of § 6 is the plan as
§ 1 to § 10 have it and does not anticipate this section: the session that builds starts at
§ 10 and can skip it. Taking the idea up is a plan of its own, after that build and on the
operator's word.

Written on 2026-09-29 by a session in the FieldnotesApp environment, at the operator's request,
after they had asked whether the Fieldnotes app could take their part of the triage. The
numbers are § 3.10's.

### 11.1 The idea

What comes to the operator and is not an action is filed in the tracker when the run ends, as
an issue in a state of its own that stands before the intake queue — working name `Proposed`.
The operator rules there, when it suits them, by moving the issue. The report keeps the
actions, which are handled when the slice is wrapped up.

The operator's words:

> I was thinking this would only be about items that are not actions. Actions are slice wrap up
> things, that really should be handled asap. Which means that basically everything that's then
> left is potential input for a card. Especially if the volume is so low, I would expect 100% to
> become either a card, or be closed. That at least simplifies the processing aspect of this,
> i.e. you don't have to go and make code changes in some environment. I would also expect only
> things that are not time critical to be handled this way.

> how does stuff come here? Because the answer is: a draft card, obviously. That means that
> Fieldnotes does become a report channel, something I explicitly excluded from the scope. So,
> we do one of two things: we expand the scope, or we send them to YouTrack with a new states
> (Draft or Proposed). The latter would be kind of obvious, assuming everything that's not
> closed, is carded.

They ruled on neither option. The session recommended the second.

### 11.2 Why the tracker, and why a state of its own

- **The tracker's states are the ruling already.** A yes is a move into the intake queue or to
  Accepted, a no is Done with the resolution Won't Do and the reason as its comment, a later is
  Later. Nothing has to carry a ruling out, and nothing is copied.
- **An unruled entry cannot stand in the intake queue.** `/dev:triage` pulls from it, and so
  does the host's nightly card pass, which works the cards it takes without the operator. Both
  ask for the intake state by name, so an issue in a state before it is seen by neither, and
  neither changes. This was read in the host's tracker convention and in the card pass's skill;
  no other reader of the tracker was checked.
- **In Fieldnotes the entry would exist three times** — in `close-out.json`, as a draft in the
  store, as a card after a yes — and would use nothing the store is for: no matching, no
  reconciler, no reactions. Its scope, what got in an agent's way and not the work, was ruled
  for reasons that still hold.
- **"A card, or closed" holds, with one shift.** Of the operator's own rulings, § 3.10's table
  brings them 30 entries that are no action: they closed 11, carded 11, folded 1 and had 7
  fixed. The 7 become cards, and a small one, once it stands in the intake queue, is what the
  card pass takes.

### 11.3 What it would change

It comes after the build of § 6, as a change on top of it: § 4.7, § 4.8 and D11 are built as
planned. The labels, both tables and the wrap-up stay as they are, since the idea starts where
the table has said "to the operator".

| | as planned | with the idea |
|---|---|---|
| § 4.7, W6 | a card request is filed on the operator's word | it is filed when the run ends, in the new state; the operator's word moves it |
| § 4.8 | Comes to you holds actions, decisions and risks; Card requests is a section beside it | Comes to you holds the actions; the rest is in the tracker, and the entry names its issue |
| D11 | rulings in the session and on the `Disposition:` lines | the same, for actions; every other ruling is the state of the entry's issue |
| the report's life | closed by the operator, after their rulings on what comes to them | closed when its actions are done; nothing waits on the rest |
| § 7, the readout | from the stores alone | from the stores, with the fate of an entry's issue read from the tracker |

### 11.4 The Fieldnotes app

The scope the operator ruled is the store's: what agents post there, and what the reconciler
curates. A second queue in the app's triage screen, which lists the tracker's issues in the new
state and writes a ruling as the issue's state and a comment, would leave that scope as it is.
It would be the first write the app makes to the tracker, which it only reads today.

It is not needed to start. At a median 2 entries a report, actions included (§ 3.10), the
tracker's own screens do. It is a second step, for when ruling there turns out to be a
nuisance.

### 11.5 Open

- **The state's name**, and what the tracker needs for it: the state, the operator's board, the
  text of the host's convention.
- **Where a yes lands**: in the intake queue, where the card pass may take the card unattended,
  or in Accepted, where it waits for `/dev:triage`.
- **What is time critical and no action.** The wrap-up asks for a card where a likely problem
  is beyond its bar (§ 4.3 row 8), and some of those are severe or graded major: 9 stood on
  that route before § 3.10's amendment (finding 26). They should not wait in a queue that is
  ruled at some point, and could come with the actions.
- **Whether an issue can be ruled from its text alone.** An entry is written for a reader who
  can ask, the operator asked advice on 39 of them (§ 3.2), and the host's convention holds a
  task's description to 200 words.
- **Who files.** A session: the tracker is reached through tools a session has and the driver
  has not. The run-slice session files the close-out card today (Job 4).

## 12. As built

Built on 2026-09-29 by one session, in the order of § 10.2: 0.9.57 (`7c32f5f`), 0.9.58
(`615074d`), 0.9.59 (`8159144`) and the research commit that holds this section. The prose is
the session's; the code is one Opus sub-agent's per commit, its diff read before the commit.
Nothing is pushed by this section's commit; the push is asked of the operator.

### 12.1 What was verified

- **`kc project test` and `kc project lint` green at every commit.**
- **The corpus through the new tool** (`close_out_readout.py corpus-check`): the 99 hand-over
  snapshots, 1,367 entries. Every entry id is in the store once and in the rendered report
  once, no body lost a line, a second render writes the same bytes, and an import reads
  nothing back. The live count per id letter is 0.9.56's in every report but KubeCoder 146,
  whose six headings without ids are entries now.
- **The tables in the tool are the tables that were tested** (`table-check`): the routes of the
  561 entries handed over, through the tool's own function, are § 3.10's route by route, and
  § 3.9's without the signal. No entry routes differently from the replay.
- **One report end to end, on a copy.** Ansible 029 and 032 had been processed by then, so it
  was 032 as it was handed over: imported, rendered, labels and a card request given by hand
  in the wrap-up's place, one ruling recorded in the session and one written on a
  `Disposition:` line and read back, both executed, the report closed, a second render the
  same bytes.
- **Not exercised, as § 7 says: the wrap-up against a repository.** And the corpus check
  renders the snapshots without labels; the committed labels were not applied first.

### 12.2 Decided in the building

As § 5's second list: settled by the building session, each as its best reading of the plan,
and named to the operator in that session's report.

| | decided | because |
|---|---|---|
| B1 | label values are written with hyphens, as the tool takes them (`ordinary-condition`, `test-gap`); the spaced form is accepted | a value is typed on a command line |
| B2 | the tool has four verbs § 6 does not name: `labels` prints the contract's section on the labels, `worklist` what waits for the wrap-up, `leave` and `close` below | the definitions stay in one place and an author reads them in one call |
| B3 | every entry the wrap-up is given ends with one mark — a strike, a card request, or `leave`: it looked and changed nothing, and says why. What it left is closed | "the rest we just close"; it is what makes *For the wrap-up* empty once it has run, and what tells a close-out session that entries still wait |
| B4 | a ruling that was executed strikes the entry, a carded one included, the reason being what was done | until now a carded entry stayed live; live now means still open |
| B5 | `close` leaves an entry live that carries a ruling nobody executed, and the report stays open over it | `defer` is the one word that keeps the card open |
| B6 | an entry the operator has ruled on does not wait for the wrap-up, whatever its route | what they ruled is theirs; met on an imported report, where the wrap-up would have been given an entry they had carded |
| B7 | § 4.4's row 1, the workflow's improvements, is a refusal of the tool and not a route; the second table opens with input for a slice | an entry the tool refuses never has to be routed |
| B8 | for an improvement, § 4.3's row 5 stands in for the wrap-up alone: what comes to the operator or is closed does so wherever the change lives | § 4.4's "rows 4 and 5 stand before it", read of its row 2 |
| B9 | in row 5 an `unknown` trigger or impact counts as one that shows and has an impact | an `unknown` is not taken for the value that closes; the replay had no `repo` label, so no tested number moves |
| B10 | § 4.4's row 3 reads "prevents something severe, or is graded major" | it is how the replay ran it |
| B11 | a soft failure of the wrap-up in the driver is all or nothing: a red gate in one repo leaves its commits out in every repo | one outcome to read, and the store taken back whole |
| B12 | in the spec repo the wrap-up commits on the branch checked out, as every agent does; a soft failure takes the store back and leaves a fold or a prose commit there where it is | that tree is shared and the store lives in it |
| B13 | in a project that runs no doc phase, a gate that is red with the wrap-up's commits and without them does not stop the run | without the wrap-up that project runs no gate there at all |
| B14 | every write to the store holds a lock on the slice directory | the close-out session records rulings while the wrap-up it dispatched strikes and relabels |
| B15 | what a loop enters with a Consequence that does not open with "none" — a funding-consult merge is one — has `unknown` labels and goes to the wrap-up to look | § 10.3, applied |
| B16 | a slice cannot be named as `for` its own entries | the entry would be folded into the slice that reports it |
| B17 | the plan loop leaves the rendered report out of its clean-tree checks, and neither loop renders while the spec repo stands on a phase branch | a render that commits nothing leaves the file modified, and a modified file refuses the next checkout |

### 12.3 What to look at in the first live slices

Beside § 7's look at the first slice. From the driver's build, none of it met in a run:

- **The wrap-up will run in most slices**: a median 5 entries a report are its own, and B15
  adds the driver's events. Its session may take up to two hours, and it adds one doc gate
  sweep, two when the first is red.
- **The gate in a repo other than the primary is `kc project test` over the whole repo and
  knows no `accept` ruling.** A repo with a red the plan accepted leaves the wrap-up out every
  time.
- **A crash between the fast-forwards and the saved outcome** resumes into the stage, takes
  the store back and dispatches the wrap-up again, over fixes that have landed.
- **What the driver guards is kept in memory.** After an interrupt, a resume does not undo a
  commit the interrupted session made on a base branch.
- **The leave-out's git calls ran against a fake only**: the reset of a moved branch, the
  discard of uncommitted work, the store read from a commit.
- **`run_loop.py status` and the dry run do not show the wrap-up.**
