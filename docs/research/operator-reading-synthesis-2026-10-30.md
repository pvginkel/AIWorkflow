# How the operator reads, answers and questions what the workflow writes them — the findings, synthesised 2026-10-30

**What this is.** The evidence base for the writing skill of the P-111 rework
(`pilot-redesign-plan-2026-10-30.md` §5.7): every finding the earlier reads made about how the one
operator reads, answers and questions the documents the workflow puts to them — close-out
reports, refinement and requirements pages, triage output, plan-loop questions. Findings only,
no recommendations; the skill turns them into rules, each rule citing its finding here. Gathered
by an Opus sub-agent from the reads named below, the operator's quotes checked against the files.

**Sources.** `close-out-read-2026-09-28.md`, `close-out-triage-plan-2026-09-29.md`,
`triage-read-2026-09-29.md`, `refinement-read-2026-09-03.md`, `plan-interview-2026-09-01.md`,
`plan-interview-rubric-2026-09-01.md`, `interventions.md`, `doc-phase-read-2026-09-04.md`; and
the operator's statement of 2026-10-30, reviewing the P-111 plan ("statement" below):

> The current requirements documents are almost useless to me. In general how I handle a
> requirements document is this: If the summary in chat is clear enough, I don't even open it and
> answer in chat. If I do open it, I read the header and try to make sense of it. That's not
> always easy. I read the proposal and determine whether it's safe enough. If so, I'll agree. If I
> have doubts, I'll read a bit of the context (most of the time I'll get half way) and leave it at
> that. The rest of a D I will read maybe 1 in 20 times, likely less. I very regularly find walls
> of text. Especially in the Card request ones. I never read those.

> Right now I very regularly get very dense prose which is nigh impossible to read. Like just a
> single paragraph of over 200 words, that would be better readable if it would be 3 paragraphs
> and 2 bullet lists.

Five sources say nothing about operator-facing documents: `readout-2026-09-01.md`,
`r1-blocking-2026-09-01.md`, `interventions-2.md`, `session-size-read-2026-10-27.md`,
`phase-count-read-2026-10-27.md`. Operator quotes are in quotation marks; "(author)" marks a
read's own words.

## 1. What the operator reads and skips

1. They read the chat summary first, and a clear one means the document is never opened. "If the summary in chat is clear enough, I don't even open it and answer in chat." — statement.
2. In a requirements doc they read the head, then the proposal, judged for safety. On a doubt they read some of the context: "most of the time I'll get half way". "The rest of a D I will read maybe 1 in 20 times, likely less." — statement. Mapping "proposal" to refinement.md's *Recommendation* and "context" to its *Context* is the synthesiser's inference.
3. Card requests are never read. "Especially in the Card request ones. I never read those." — statement. No read has looked at card-request text (see 4.15).
4. In a close-out report they read the entries only. Focus line: "I don't read it, at all." Head and card body: "I don't read the close out card body, or the head of the report. A list of entries is enough for me." Summary: "I don't read the summary." — close-out-triage-plan § 2.
5. **Contradiction.** The close-out read treated the Focus line as a signal the operator's rulings track. The later plan found it was never read, so its "first pick progressed 60 %" is agreement between two judges, not anchoring. The read's 87–89 % was also measured with Focus lines visible to the sorter. — close-out-triage-plan § 3.1, findings 1–3.
6. They read every close-out entry and "judge the items at their merit". An entry costs a median 163 words whatever its fate, and 63 % of the words read belong to entries they close. Two thirds of closes (432 of 665) name no entry ("I'm not progressing the rest"). — close-out-read § 2, findings 2–3.
7. Fatigue drives the hand-overs. About 2/3 of auto close-outs happen because "I'm doing the third or fourth close out report in a sitting and I'm fed up with them". — close-out-triage-plan § 2.
8. They hardly read triage documents: "I hardly read them." A 12.7k-word document was ruled 28 minutes after its commit, against about 51 minutes at reading speed; a 7.8k-word one in 18, against 31. — triage-read § What the document's own machinery contributed.
9. The 0.9.19 refinement docs were 27–35 KB. Four were read cold the next morning between 05:37 and 06:01. The design assumed the operator would read the grounds and refute them; that did not happen. — refinement-read § Corpus; § What the read says.
10. Long design documents go unread too. The operator ruled D1–D11 of a plan without reading it (author: "They had not read this document — they took it to say what was discussed"). — close-out-triage-plan § Status.
11. Inside a fresh slice, bare handles (D-ids, R-numbers, file:line) cost nothing. Grader: "the operator absorbs handles fine on his own repo". Cold, they do cost: 52 % of plan questions were not readable cold, and confused, delegated or dismissed answers rose from 11 % (self-contained) to 16 % (leaning on handles) to 21 % (needing earlier chat). — rubric § Session notes / Ansible_016; plan-interview § 2.
12. A median plan dialog put 2.3 KB of questions and options after 1.8 KB of prose. The median answer took 4.9 minutes (p90 20.6); one sat overnight for 524 minutes. — plan-interview § 2.
13. **Ambiguity, not a contradiction.** Today "I read the header" (requirements doc); in September "I don't read … the head of the report" (close-out). These are different documents. — statement; close-out-triage-plan § 2.

## 2. How they answer

1. Triage, 181 items: agree 80, answer 44, cull 23, no ruling 17, bounce 11, steer 6. Half of what they typed in the document was "Agree" (58 times). — triage-read § What the operator did; § Where the operator ruled.
2. Substance came almost only where a question was asked. Of 72 asked items, 41 got an answer; of 109 unasked, 72 got "agree" and 3 an answer. — triage-read.
3. Plan interview, 231 questions with a recommendation: 77 % took it, 8 % a listed alternative, 12 % a typed answer. Deviation was 19 %, and 31 % on relayed writer questions. Of 55 typed answers, 19 asked back and 16 said context was missing ("I need background for this also", "I'm missing context"). — plan-interview § 2.
4. Refinement on 0.9.19: 12 decisions, 0 deviations, 1 in-file comment, 2 delegations. "Accept all as-is. … I trust you get this right." "I don't have the faintest about the other one. I assume you know what you're doing." The operator's own reading: "Assume the low number of responses is to a large degree due to me not understanding the document." — refinement-read.
5. The delegation phrases recur. "I don't know. Please pick a low cost pragmatic solution." "Basically just don't over engineer this. Pick the simple option". "I read all your options and I don't know. I want to follow your recommendations." — rubric (160, 163); plan-interview § 2 (194).
6. Handed a sheet, they defer: they changed 4 % of its proposed closes (10 of 229). On their own reading they progressed 22 % of what the same sort closes. They followed 35 of 41 advice recommendations. — close-out-read § 4, finding 11; § 5, finding 17.
7. Progressed share by whose ruling: their own 48 %, after asking advice 51 %, from a sheet 30 %, the rest of a mixed or auto session 27 %. — close-out-triage-plan § 3.2.
8. Their stated policy: prose and safe nits always progress; easy-fix bugs always; the rest by likelihood. "High severity needs to come to me, even if it's very unlikely." Silent problems are progressed at 51 %, loud ones at 24 %. — close-out-triage-plan § 2; § 3.10.
9. Some closes are about effort, not judgment: "quite a few items I close because I don't feel like putting in the effort to progress them." — close-out-triage-plan § 2.
10. Where they answer: triage was ruled in the document in 10 runs and in chat in 9, and the last five runs all in chat. On close-outs: "Both are fine. … It's in-context for me." Offered dialogs on design questions, they typed free text or dismissed the dialog (8 of 19). — triage-read; close-out-triage-plan § 2.
11. Free text carried what shaped the slice: "Cut R2, R5 and R6", "HelmCharts will go. We can manage in the mean time", new requirements in the notes box. — plan-interview § 2, What free text carried.

## 3. The questions they ask back

1. Close-out advice requests (49): what the entry says (16), whether it can happen and how bad it is (13), whether the fix is cheap and worth it (11). "I also don't know what the effort is to fix this." "I can't see whether this is transient and auto fixes itself in a short period." — close-out-read § 4.
2. Whether the problem is real, or overbuilt. "Are we just over complicating this?" (the coordination design was deleted). "Is there a simpler solution, or is there maybe not really a problem?" "which of the issues we're looking into are actually problematic, or are maybe just quirks". — plan-interview § 2; rubric (145, 146).
3. Size: "How big is this slice taking the answers into account?" The slice went back to triage. — plan-interview § 2.
4. Missing context, a link or a term. "Can you give me an url to #606?" "What's the self action token?" "Can you give me the pros and cons". "Please walk me through this". — plan-interview § 2; rubric.
5. Why is this here, and why this way. "Why would you want to bring these to me?" "Why would we want to make this optional? If we add this, the default is ON." "I'm asking why not." On a label: "I don't know. Does it matter?" — close-out-triage-plan § 2; triage-read.
6. They bring designs the document did not offer: "we're removing the explorer.exe prefix, right?"; "I want a third option". — refinement-read § Corpus; rubric (189).
7. A label of `unknown` does not mark what they cannot judge: of the 33 entries they asked advice on, 2 carried one. — close-out-triage-plan § 3.3, finding 9.

## 4. The complaints about the writing itself

1. Walls of text and dense prose. "I very regularly find walls of text." "just a single paragraph of over 200 words, that would be better readable if it would be 3 paragraphs and 2 bullet lists." — statement.
2. Refinement: "this is just a wall of text I can't make heads or tails of … I really don't believe it has value. It shouldn't be necessary." In 3 of 5 docs over half was the opener, which checked premises at file:line and quoted functions whole; slice 199 had more code lines than prose. — refinement-read.
3. Close-out: "I find the reports laborious to go through." "The document is huge and I'm worried I'll miss something." "a whole bunch of nits on prose that shouldn't even be there." The live part ran a median 2,867 words (p90 5,375). — close-out-read head; § 2; § 4.
4. Reports are not questions. "just a dump of thoughts and ideas. They aren't questions." "the agent isn't really taking responsibility for what it's reporting." — close-out-triage-plan § 2.
5. **Contradiction.** The close-out read found length predicts nothing (shortest quarter progressed 38 %, longest 41 %), advised against a prose cap, and put the labour in the number of entries needing no decision. The operator, today and in the refinement verdict, puts it in prose density. The read measured length against outcome, not readability. — close-out-read § 2, finding 2; § 7; statement.
6. Triage: "I feel like the triage reports have little value … what's really decided in the documents?" Card text was 56 % of the words. — triage-read.
7. Plan dialogs, in the operator's brief: they corner the reader, cut code off, assume the slice is fresh, and pad with alternatives. "I'm doing this from (bad) memory. … this isn't really productive". Padded options such as "Reject — leave the plan wrong" were accepted 9 of 9. — plan-interview head; § 2.
8. Unexplained handles: 145 of 317 questions leaned on them; relayed writer questions were 22 of 27 not readable cold. — plan-interview § 2.
9. Premises written inside options read as background, not as claims to check. 15 rested on a false premise: "Testing complete. I'm connected using SSH right now"; "I don't know why you wouldn't see it." — plan-interview § 2; rubric (Ansible_006).
10. Settled lists and grounding. "mostly noise … A far more compacted version (one sentence per item) I may read, but even then I'm not sure." "I should not have to see the details. The planner agent will have this already." — refinement-read § The ruling.
11. Decisions that were not theirs: 8 of 12 were implementation picks whose own alternative lines said "Loses" or "not worth it". — refinement-read.
12. Severity was hidden. "It would of course help a lot if this information is clearly visible, right?" — close-out-triage-plan § 2.
13. The signal they fear missing: "an agent trying to get my eyes on something that I then don't see … it's not immediately obvious what it feels is important I look at." — close-out-triage-plan § 2.
14. Padding suspicion: "a model inventing (padding out) work, as it tends to do." This was about doc edits, and the read refuted it there (hedge words 0.19 % → 0.12 %). — doc-phase-read § 6, finding 22.
15. Evidence gap on card requests. The plan leaves open "whether an issue can be ruled from its text alone": an entry is written "for a reader who can ask", and the host's convention caps a task description at 200 words. — close-out-triage-plan § 11.5.

## 5. What made a document or an ask useful to them

1. The asked-for shape: "Summary and decisions (with context) is what I'm looking for." **Tension:** the close-out Summary was unread ("I don't read the summary"), and today it is the chat summary that decides. — refinement-read § The ruling; close-out-triage-plan § 2; statement.
2. An explicit question. Collisions with a standing decision (33 items) "produced the real rulings". — triage-read § What the operator did.
3. Decisions that change what a user sees or what the operator runs were the only ones engaged with (4 of 12). — refinement-read.
4. Evidence inside the ask. Grader: "The dialog format cost almost nothing here because each question carried its own numbers" (168). Narrow forks local to one file, with the operator inside the slice, were answered in a minute or two. — rubric (168, 186); plan-interview § 2, Where it cost nothing.
5. Prose before a re-ask: three re-asks worked "because a page of prose came first". — plan-interview § 2.
6. Advice that traced reach and priced the fix: "B1 is unreachable, not just extreme", with a six-line fix recommended against. Such advice was followed 35 of 41 times. — close-out-read § 4.
7. One line per item, with numbered questions, in chat. This was ruled the triage format, and an 18-item run was ruled by numbered reply. Dialogs did work for grouping picks. — triage-read.
8. A short list named at the close of a session was ruled at once: "I don't read the summary. / I don't need the switch." — close-out-triage-plan § Status; § 2.

## 6. Removed or shrunk since, and the read that showed it

1. The dialog tool in plan-slice, replaced by refinement.md (0.9.19). Grounds: 52 % not readable cold, 9 dismissals, 8 of 10 relapses into dialog. — plan-interview § 2; § 4.1; § 5.
2. Accept/reject pairs and padded alternatives (0 of 13 rejected; listed alternatives won 8 %). Alternatives now appear only when live. — plan-interview § 2; § 4.2–4.3.
3. The refinement opener "Where we are" (870–2,626 words) became 1–3 paragraphs. Grounding detail moved out, the "code in full" rule went, the decision bar rose to what the operator could rule the other way, and the settled list became one sentence per item, filtered (0.9.21, target under 1,200 words). No re-read of 0.9.21 was found. — refinement-read § The ruling.
4. The triage status document became one chat message (0.9.60). Shown useless with it: the category labels ("predicted nothing"), `Note:` lines (on 105 of 181 items, 3 reactions), the adjudicate-now/dispose-later seam (used once), and `triage_verbatim.py` (663 lines). — triage-read.
5. Close-out Focus lines, Summary, and the sheet at the report's head and in the card body: removed by ruling. Already 174 of 489 Focus lines sat over empty sections, at a median 27 words each. — close-out-triage-plan § 4.9; close-out-read finding 4.
6. Clean-round Notable events, no longer recorded (progressed 6 %), and already-fixed entries, now struck by whoever fixed them (58 entries, 10,500 words) (0.9.56). — close-out-read § 3, findings 7 and 9; § 7 R2–R3.
7. What reaches the operator: a median 2 of 11 entries, with closed entries folded to one line. — close-out-triage-plan § 3.9; § 4.8.
8. **Contradiction.** The original close-out design expected "Focus lines and ids" to keep the report from becoming "a document nobody reads". The operator never read the Focus lines. — interventions § 6 C7; close-out-triage-plan § 2.
