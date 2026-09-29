# The close-out report against the operator's rulings (read, 2026-09-28)

The operator's question: "If I ask for a fast close out, or advise during close out, I get quite
different rulings from what's suggested in the close out report. Why is this, and can this be
leveraged to trim it down, possibly using a post processing step? … I find the reports laborious
to go through."

**Status: ruled 2026-09-29, and overtaken in part.** The operator took the four
recommendations of § 7 — "I like the changes that are suggested here". R2 and the author side
of R3 are built (0.9.56). R1 and R4, the sort of § 6 and the rules of the appendix are not
built and will not be: in the discussion of this read the operator ruled for labels given by
an entry's author, a policy table in the tool and a wrap-up phase. That is
[close-out-triage-plan-2026-09-29.md](close-out-triage-plan-2026-09-29.md), ruled and to be
built; its § 3 scores § 6 of this read again, against the rulings that are the operator's own,
and corrects finding 17's 9 %. § 8 says what this read does not show.

**The answer in short.**

1. **The rulings differ because the report and the session answer different questions.** The
   report's authors are asked what they noticed, under "in doubt, add it"; its Focus lines rank
   the entries against each other and name 78 % of them. Nothing in a report ever says "close".
   The session is asked what should happen to each entry, against the operator's bar, and it
   does work the entry's author did not: whether the thing can be reached, whether it still
   holds, what the fix costs (§ 4, § 5).
2. **Part of the difference is the operator's own.** Handed a sheet, the operator changes 4 % of
   its proposed closes. Reading the report themselves, they progressed 22 % of the entries the
   same sort would have closed (§ 6).
3. **As a filter the sort cannot be trusted; as an ordering it can.** Run from the report alone
   under the skill's current rules, it keeps 63 % of what the operator progressed on their own
   reading. What it loses falls into four classes, three of which a rule fixes. With those
   rules, on thirty reports the rules were not derived from, it keeps 87 %, and what it still
   closes is progressed at about a tenth, against four tenths for what it flags (§ 6).
4. **What can be trimmed without any judgment is about an eighth**: entries the run already
   fixed but could not strike, Notable events whose own consequence is none, Focus lines over
   empty sections (§ 3, § 7).

## 1. Corpus and method

**Reports.** Every `close-out.md` in `KubeCoderSpecs` (76, slices 146–236) and `AnsibleSpecs`
(23, slices 008–032) at their heads of 2026-09-28: 99 reports, 1,429 entries.
`close_out_readout.py extract` reads each entry's section, severity, evidence class, author
role, Consequence line, strike reason and `Disposition:` line, and classifies its fate from the
words on the heading and the disposition. The classifier is a list of patterns over free text:
against the 197 rulings the session coding below names entry by entry it agrees on 88 %, and
on progressed-or-not on 92 %. Shares below are good to a few points, not to the entry.

**The report as handed over.** `snapshots` recovers each report from the spec repo's history as
the run left it: the newest commit in which no `Disposition:` line carries words. Eleven
snapshots predate the run's final stamp (the operator's first disposition shared a commit with
later entries), so they hold fewer entries than the final report.

**The close-out sessions.** `sessions` finds the interactive transcripts that struck entries or
wrote dispositions — 80 of them, 61 KubeCoder and 19 Ansible — and reduces each to a digest: what
the operator typed, the assistant's prose, the strikes. Four Sonnet readers coded the digests to
one schema (mode, the sheet the session proposed, the rulings the operator named, overrides,
advice exchanges, entries found stale, the operator's remarks about the reports). Seven of the
80 turned out to be other work; 68 reports have a coded session.

**The replay.** An Opus sub-agent per batch of five to seven reports sorted the hand-over
snapshots into proposed dispositions, from the report alone — no repository, no dispositions
visible. Three arms: the skill's current rules on 55 reports; the same rules on 30 held-out
reports; revised rules (the appendix) on those 30. Twelve reports were sorted twice under the
same rules to measure the sort against itself. "Ruled by the operator's own reading" below means
the coded session was `direct` or `mixed` — the operator named their picks — and is the
independent half of the evidence: on a report ruled from a sheet, the ruling is anchored on a
sort like the one being tested.

Every table regenerates from `docs/research/tools/close_out_readout.py`, except the sorts and
the session coding, which are model judgments: their ids and buckets, without entry text, are in
`docs/research/data/close-out-read-2026-09-28.json`.

## 2. What a report costs to read, and what comes of it

| at hand-over | median | p75 | p90 | max |
|---|--:|--:|--:|--:|
| live entries | 10 | 15 | 21 | 56 |
| words, live part | 2,867 | 3,844 | 5,375 | 12,352 |

Summary and Focus lines add a median 211 and 236 words. Of 1,429 entries:

| fate | entries | |
|---|--:|---|
| struck in-run (consult, doc phase, refuted, superseded) | 258 | 18 % of all |
| closed at the operator's pass | 665 | 64 % of the 1,038 ruled |
| fixed inline | 179 | 17 % |
| carded | 163 | 16 % |
| folded into a slice or handover | 31 | 3 % |
| an Outstanding action carried out | 55 | |
| still blank | 63 | 50 on two Ansible reports not yet processed (029, 032), 8 on slices still running |
| deferred, unclassified | 15 | |

1. **A third of what is ruled is progressed, steadily**: 32 % / 36 % / 32 % across the three
   eras (before the standing rules of 08-30, with them in session memory, since 0.9.38). Per
   report the median is 3 progressed entries of 11; twelve reports progressed none.
2. **Every entry costs the same to read whatever becomes of it.** Median 163 words, and the
   median is 162 for entries closed, 158 fixed, 172 carded. 63 % of the words the operator reads
   belong to entries they close. Length predicts nothing: the shortest quarter is progressed at
   38 %, the longest at 41 %.
3. **Two thirds of the closes name no entry.** 432 of 665 are a blanket ruling ("I'm not
   progressing the rest") — the operator read them and had nothing to say.

## 3. What the report's own signals predict

Progressed share of the entries ruled (card + fix + fold):

| signal | entries ruled | progressed | carded or folded |
|---|--:|--:|--:|
| all | 1,038 | 36 % | 19 % |
| Bug · major | 9 | 67 % | 56 % |
| Bug · minor | 147 | 58 % | 31 % |
| Bug · nit | 145 | 31 % | 3 % |
| Suggestion | 522 | 40 % | 23 % |
| Notable event | 140 | 6 % | 4 % |
| `Consequence:` says none | 270 | 17 % | 7 % |
| `Consequence:` states one | 706 | 43 % | 22 % |
| witnessed | 395 | 28 % | 14 % |
| read | 475 | 43 % | 21 % |
| author test-agent | 63 | 8 % | 0 % |
| author consult | 26 | 8 % | 4 % |
| author doc-writer | 73 | 62 % | 18 % |
| named first in its section's Focus line (Bugs, Suggestions) | 157 | 61 % | |
| named later in the Focus line | 477 | 39 % | |
| not named in the Focus line | 194 | 36 % | |

4. **The Focus line summarises, it does not select.** It names 78 % of the entries handed over.
   Only its first-named entry carries signal — 61 % against a 37 % base; being named later is
   worth nothing. 174 of the 489 Focus lines stand over an empty section and spend a median 27
   words saying so.
5. **Severity separates carding, not reading.** A nit is carded 3 % of the time and fixed inline
   28 %; a minor is carded 31 %. Both cost the same words.
6. **`witnessed` is progressed less than `read`** (28 % against 43 %). The evidence class says
   how sure the claim is, not how much it matters: witnessed entries are disproportionately test
   gaps shown by mutation and records of a run's events.
7. **Four classes are close to never progressed**: Notable events (6 %), the test-agent's entries
   (8 %), the consult's (8 %), the driver's (0 of 8). 82 of the 140 Notable events ruled say
   their own consequence is none; of those 82, two were fixed inline and none was carded. About
   40 are records of something that went right ("Test phase r1: rebase, push, CI, dev deploy,
   and live verification all clean").
8. **No mechanical rule beyond those is safe.** Folding every nit loses 11 % of what is carded,
   every `Consequence: none` 10 %, both together with Notable events 22 %.
9. **58 live entries in 25 reports were already fixed when the report was handed over** — 5 % of
   what the operator reads, 10,500 words. 48 carry a doc-writer note ("Fixed in 1672029"): the
   doc phase runs after the completion consult, and only the consult strikes. One Focus line
   calls two of them "strikes waiting to happen, not open work". The operator ruled "fix inline"
   on 13 of them.

## 4. What the sessions propose, and what the operator does with it

Of 73 close-out sessions, 26 are `direct` (the operator names entries and dispositions), 26
`mixed` (names some, has the session propose for the rest), 15 `handed-over`, 5 `auto`, 1 a
blanket close. The share with a sheet grew: 6 of 21 sessions before 08-30, 9 of 14 since 09-18.
Reports handed over are the larger ones — a median 16.5 entries against 10 for those ruled
directly.

**The sheets.** 32 sessions proposed a disposition for 359 entries: close 64 %, fix now 13 %,
card 11 %, fold 6 %, needs-your-eyes 4 %. That is the operator's own rate — they close 64 % of
what they rule. Against the report's signals:

| the sheet proposed, for entries… | n | close | fix now | card | fold | needs eyes |
|---|--:|--:|--:|--:|--:|--:|
| named first in their Focus line | 70 | 47 % | 7 % | 27 % | 9 % | 4 % |
| named later | 188 | 66 % | 15 % | 8 % | 6 % | 3 % |
| not named | 100 | 72 % | 14 % | 3 % | 4 % | 5 % |
| Bug · minor | 62 | 47 % | 13 % | 24 % | 10 % | 5 % |
| Bug · nit or cosmetic | 63 | 65 % | 29 % | 0 % | 3 % | 3 % |
| Suggestion | 151 | 62 % | 11 % | 13 % | 9 % | 3 % |
| Notable event | 51 | 94 % | 4 % | 0 % | 0 % | 2 % |
| `Consequence:` none | 90 | 86 % | 9 % | 4 % | 1 % | 0 % |

10. **The sheet follows the report's ranking and then does what the report never does.** It
    cards the first-named entry nine times as often as an unnamed one — and still closes it
    47 % of the time, as it does a `minor` bug.
11. **The operator follows the sheet.** 30 overrides on 359 proposals; leaving out one report put
    off whole ("No. I will run the close out later") and four about whether an action was
    already done, 18 (5 %). Of 229 proposed closes, 10 were pulled back into a fix, a card or a
    fold (4 %).
12. **At close-out the session finds what the run could not know**: 74 entries in 30 sessions
    were already fixed, already done or no longer true when it checked. And in 40 sessions it
    flagged 55 entries on its own initiative as the operator was about to close them.

**Advice.** 49 exchanges on a named entry. What the operator asks: what the entry is saying (16),
whether it can happen and how bad it is (13), whether the fix is cheap and worth it (11).

> B1 seems like an extreme scenario, something that realistically won't be reached. I however
> can't really determine this. I also don't know what the effort is to fix this.

> I can't make a good determination for B4. I can't see whether this is transient and auto fixes
> itself in a short period.

The session answered the first with "traced all four preconditions; two contradict each other in
production, so B1 is unreachable, not just extreme", and a six-line fix it recommended against;
the second with "B4 self-heals … seconds after a controller roll", and for its neighbour B6 "no
time bound", card. Of 41 exchanges with a recommendation and a known ruling the operator followed
35; the recommendation was close in 17, all followed.

**The operator on the reports**, from the sessions:

> I'm ignoring large parts of close out reports (meaning I read them and decide fixing the nit or
> cosmetic is not worth the effort). On this one I'm honestly not sure.

> The document is huge and I'm worried I'll miss something.

> There's a lot in this close out and I can't be sure if there's anything we need to progress.

> Regarding the rest it seems like a whole bunch of nits on prose that shouldn't even be there.

## 5. Why the rulings differ

13. **The report is written by finders, one phase at a time.** Each author sees its own phase,
    is told "in doubt, add it", and pays nothing for an entry. None is asked whether the operator
    should spend on it, and none can weigh it against the other thirty. The `Consequence:` line
    asks what happens *if*; 27 % of the lines ruled rest on "today", "only if", "until" or
    "latent", and those entries are progressed at 27 %.
14. **The report ranks, the session rules.** "B2 first (the only minor)" is true of a section in
    which, on the sheet of the same report, "nothing here has an observable consequence today"
    (slice 180). Both statements are right. Only the second is a disposition.
15. **The session's answer costs work the entry did not get.** Reach, staleness and the price of
    the fix are what the operator asks for and what the sheet's why-clause carries. The sheets'
    reasons for a close, by the words they use: already fixed or settled (56), no impact (36), a
    test gap (24), remote (15), other (96).
16. **The session knows the operator's bar.** The standing rules of 2026-08-30 — known small
    changes fixed, real impact carded, edge cases and nits closed, suggestions mostly closed —
    reach the close-out session and no author.
17. **On a sheet the operator defers.** Finding 11 against § 6: the same person who changes 4 %
    of a sheet's closes progressed 22 % of what that sort closes when the entry itself was in
    front of them. The report makes a case for every entry, and the sheet makes one against most
    of them; which is nearer to what the operator wants cannot be read from the record.

## 6. The sort as a post-processing step — the replay

**The skill's current rules**, 85 reports, sorted from the hand-over snapshot alone:

| | all | ruled by own reading | ruled from a sheet |
|---|--:|--:|--:|
| reports | 85 | 65 | 20 |
| entries ruled | 942 | 630 | 312 |
| the sort closes | 59 % | 59 % | 59 % |
| … of which the operator progressed | 20 % | 22 % | 15 % |
| progressed entries the sort kept | 67 % | 63 % | 75 % |

18. **The sort is stable and systematically off.** Sorted twice, 138 of 146 entries land in the
    same bucket and 5 change between closed and flagged. The disagreement with the operator is
    not noise.
19. **It ranks well.** What it flags is progressed at 58 %, what it closes at 20–24 %. Read in
    its order, the operator meets their own picks two to three times as densely at the top.
20. **It loses a third of them if its closes are taken unread.** On the first 55 reports, 21 had
    every progressed entry flagged; over all 55 the loss is a mean 1.5 a report.
21. **The 82 entries lost on those 55 reports are four classes**, not counting 25 that were
    already fixed when the operator asked for a fix:

    | class | entries | what the operator did |
    |---|--:|---|
    | a small known change with no consequence | 23 | had it fixed on the spot — a nit with a one-line fix is sorted `close` on its Consequence, while the operator's rule fixes it because it costs less than deciding |
    | input for a slice still to run | 18 | folded it into that slice — the skill's sort has no `fold` bucket |
    | a test gap | 15 | carded them, several to a card ("file these as one test gap card") |
    | the operator's own call | 26 | carded a remote edge case anyway, or turned a nit into a product decision: "it should just open the configured shell", "card S3 as a card to instead remove the feature from the product" |

**Revised rules**, on the 30 held-out reports (the appendix has them): an order of buckets, the
first that fits — `moot` (the entry says it was fixed in-run), `action`, `fold`, `fix now`
whatever the consequence, `test gaps` as one group per report, `card`, `needs-eyes` including
any entry that proposes removing or redesigning something, `close`.

| 30 held-out reports, 353 entries ruled, 104 progressed | current rules | revised rules |
|---|--:|--:|
| the sort closes (`close` + `moot`) | 61 % | 36 % |
| … of which the operator progressed | 13 % | 9 % |
| progressed entries the sort kept | 73 % | 89 % |
| … carded or folded | 75 % | 91 % |
| … fixed inline | 71 % | 88 % |
| — on the 21 reports ruled by own reading | 68 % | 87 % |
| reports with no progressed entry closed | 11 | 21 |
| progressed entries closed, per report | 0.9 | 0.4 |
| words to read: needs-eyes, card and action whole, a line for the rest | 36 % | 37 % |

| revised rules, by bucket | entries | progressed |
|---|--:|--:|
| card | 32 | 72 % |
| fix now | 69 | 54 % |
| needs-eyes | 40 | 38 % |
| fold | 26 | 38 % |
| test gaps | 44 | 14 % |
| action | 14 | 14 % |
| close | 105 | 9 % |
| moot | 23 | 9 % |

22. **Three rules recover most of what was lost**, out of sample: the kept share rises from 73 %
    to 89 %, and the reports sorted without a loss from 11 to 21 of 30.
23. **The revised sort errs toward doing the small thing.** It proposes `fix now` for 20 % of
    entries where the operator had 14 % fixed; 32 of its 69 fix-nows the operator had closed. A
    "Go" on such a sheet has the session make about one and a half times the inline edits the
    operator used to ask for — doc, comment and test text.
24. **What remains is the operator's.** The eleven progressed entries the revised sort still
    closed are calls no rule predicts: "`/create` should exit to Environments. Please file.",
    a doc-size nit carded "possibly as a general pass". That is 0.4 entries a report, and the
    reason a close stays a proposal.
25. **The reading drops to about 37 % either way**: the entries that need the operator's eyes in
    full, one line — headline and why — for the rest. The revised rules do not shorten the
    sheet; they change what a "Go" does.

## 7. Options and recommendation

**Recommended, in this order.**

**R1 — The sheet is how `/dev:close-out` opens, under the revised rules.** Prose only, in the
skill: step 2 presents the sorted sheet instead of `list`; the section for a handed-over triage
becomes the procedure; the sort takes the order of the appendix. The operator already works this
way on the large reports, and the staleness check of finding 12 comes with it, which no step at
the end of a run can make for a report ruled days later. It costs a wait of three to four minutes
at the start of a close-out. Finding 17 is the price: the rulings become the sheet's unless the
one-line list is read, and finding 24 says it should be.

**R2 — Whoever fixes an entry strikes it.** Finding 9: the doc-writer strikes what its own
commit resolved whole, through `close_out.py strike`, the reason naming the commit as the
consult's does; what it fixed in part keeps its note and stays live — four of the 58 were carded
or folded for the half the fix had left. A contract change (`close-out.md`: "only the completion
consult strikes") and a line in the doc-writer's register; the render that follows the doc phase
already folds struck entries.

**R3 — A pass that went right is not an event, a Notable event without a consequence is a
headline, and an empty section needs no Focus line.** Finding 7: the test-agent's register stops
recording a clean round — the section charter already says so ("what happened to this run that
an uneventful one would not have had") — and `render` shows a Notable event whose `Consequence:`
is none as its headline, the body folded as a struck entry's is. Finding 4: the doc-writer
writes `Focus: none` over an empty section. With R2 that is 137 of the 1,137 entries handed
over, 12 %, and 13 % of their words; of the 80 Notable events among them none was carded.

**R4 — The sort at the end of the run: after R1 has run on some slices, not before.** The
post-processing step the question asks about would be a dispatched session after the doc phase,
fresh, with the report alone, writing the sheet into the report's head and the close-out card's
body in place of the Focus lines, with `render` ordering the entries by bucket and folding none.
The replay is that step, and it priced at roughly 20 k tokens a report. It is the same sort as
R1's, so R1 tests its rules in production at no build cost; what R4 adds is that the card says
what is waiting before a session is opened. It must keep the constraint of 2026-08-17 — it ranks
and pre-fills, never closes — which findings 20 and 24 now put a number on.

**Not recommended.**

- **Closing or dropping entries on the sort's word.** It costs a third of the operator's picks
  under today's rules and a tenth under the revised ones.
- **Raising the bar at the source** ("in doubt, add it" → a threshold). The author has the least
  context of anyone in the chain (finding 13), and what it drops nobody sees. The decision of
  2026-08-15 stands on this read.
- **New labels on the entry** (`Reach:`, `Fix:`). The Consequence rule already asks for what has
  to happen for it to be reached; the answer takes the tracing the close-out session does, which
  an author in the middle of a phase would do for every entry instead of the fifth the operator
  asks about.
- **A cap on prose.** Length predicts nothing and is uniform (finding 2); what is laborious is
  the number of entries that need no decision.

## 8. What this read does not show

- **Which ruling is right.** The read measures agreement with what the operator did. Whether
  the entries they progress on their own reading and would have closed from a sheet were worth
  progressing is theirs to say (finding 17).
- **Whether one line is enough to catch the eye.** The 37 % assumes the operator spots, from a
  headline and a why-clause, the entry they would have picked from its body. Untested.
- **The sort with a repository.** The replay sorted from the text; the production sheets also
  checked the tree. Their kept share cannot be measured — the operator ruled on them — but on
  reports ruled from a sheet the text-only sort agrees with the outcome more (75 %) than on
  those ruled by own reading (63 %).
- **The doc-writer as the sorter.** Every sort here ran in a fresh session holding one batch of
  reports. A sort written at the end of a 200 k-token doc phase is a different measurement.
- **Ansible since 09-18.** 50 blank entries on reports not yet processed are outside every
  share.
- **The fate classifier** is pattern-based (§ 1), and "already fixed" is read from the
  disposition's wording.

## Appendix — the revised sorting rules, as replayed

Sort every live entry into one bucket. Take the buckets in this order — the first that fits is
the entry's bucket:

1. **`moot`** — the entry itself says the thing is already done: a dated note under it (or its
   own body) says it was fixed, resolved or closed during the run and names the commit or the
   phase. Nothing is owed; it only waits to be struck.
2. **`action`** — every Outstanding action (section A): they all go on one card in the
   operator's action queue, a list they work from.
3. **`fold`** — the entry is input for work that has not run yet: it names a slice or a phase
   still to come, or says what a later slice, migration or plan has to take into account. It is
   appended to that slice, whatever its size.
4. **`fix now`** — a small change whose content is already known: the entry says what the text
   or the line should be. Doc, comment, config and test text above all. **The size of the
   consequence does not move an entry out of this bucket**: a nit whose fix is one known edit is
   a `fix now`, not a `close` — the operator has such edits made on the spot because they cost
   less than deciding about them.
5. **`test gaps`** — the entry's whole claim is that a test is missing, pins nothing, or cannot
   fail, and the code it would guard is right today. All of a report's test gaps are one group,
   ruled on together: the operator cards the group as one card or closes it.
6. **`card`** — a bug with real impact that is not a `fix now`: its Consequence names something
   an operator or user will meet in the deployed shape. Entries that are one fix are one card.
7. **`needs-eyes`** — what the operator has to look at themselves: a bug whose impact the entry
   does not let you judge, an open question or ruling, an entry that proposes removing,
   simplifying or redesigning something (a product call is theirs), the suggestion that is
   clearly interesting, an entry two buckets both fit. Do not force these — this set is what the
   sheet is for — and keep it small: a set that is a third of the report means the sorting was
   not done.
8. **`close`** — everything else: edge cases that are real but remote, nits and cosmetics with
   no known one-edit fix, records of things that went right, and Suggestions by default — a
   suggestion is closed unless one of the buckets above took it.

The current rules, as replayed, are the skill's own (`plugins/dev/skills/close-out/SKILL.md`,
"When the operator hands you the triage", step 2) with step 1's check of the tree left out.
