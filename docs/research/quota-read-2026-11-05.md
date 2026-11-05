---
status: read 2026-11-05, no ruling asked — the operator starts collecting the usage endpoint's readings the same day, and a few weeks of them replace this method
---

# Does our computed cost add up to the same quota every week? (read, 2026-11-05)

**Finding.** Yes. Our cost comes out about the same in every week that used up the subscription.
Prices are the plugin's own (`slice_cost.cost_for`). Such a week came to about **$2,020 before
the 2026-09-14 quota change and $1,900 after**, each within ±6 %.

Two things the data does not settle:

- **The 2026-09-14 change shows as −6 to −8 %, not the −17 % announced.** On the same model,
  Opus 5.1 before and after, it shows as −12 %. Either claude.ai's share moved, which no
  transcript shows, or the quota counts Opus 5.5 7–14 % lighter, relative to 5.1, than our price
  table does. A dollar comparison across the 5.1 → 5.5 switch carries that much slack.
- **The 2026-05-13 increase cannot be seen.** No week before it came near the limit.

## What was summed

- **Every transcript under `~/.claude/projects`** written since 2026-01-01. The directory is
  shared across every environment on this host and holds the laptop's sessions too: 19,186 files
  and 576k assistant messages, each counted once by message id.
- **Each message priced with `slice_cost.cost_for`,** long-prompt tier included. Fable is counted
  with the rest. It draws from the main quota and its own at once, and stops when either runs out
  (the operator, 2026-11-05).
- **Summed per quota week, starting Thursday 10:00 UTC.** The limit messages say "resets 12pm"
  Amsterdam time in summer and "resets 11am" after the clocks went back on 2026-10-25, so the
  boundary is fixed in UTC.
- **Limit hits come from the transcripts themselves.** They are `<synthetic>` assistant
  messages, for example "You've hit your weekly limit · resets Oct 15, 12pm (Europe/Amsterdam)".
  They give the weeks that ran out and the hour they did.
- **Left out of every comparison:** a week holding one of the free resets Anthropic granted.
  These were Feb 27, Apr 17, Apr 23, May 15, Jun 1, 9, 13 and 19–20, Jul 1, 9 and 16, Sep 1 and
  Sep 4. Also left out is the week of Oct 8, where the banked Opus 5.5 reset was used on hitting
  the limit on Oct 12 and which held a lot of claude.ai work. The Jul 9 and Jul 16 resets fell on
  the week's first Thursday at an unknown hour. Those two weeks count as a range: without and
  with that day's spend.
- **Not in it:** claude.ai, and any Claude Code session outside this home directory. The
  operator put claude.ai at about 5 % in the week of Oct 29. Other weeks are not known, and the
  week of Oct 8 was heavy.

## The weeks that ran out

The cost from the week's start to the weekly hit:

| Week from | Weekly hit (UTC) | Cost to the hit |
|---|---|---|
| Jul 16 | Wed Jul 22, 20:20 | $2,051–2,279 (the Jul 16 reset fell on its first day) |
| Aug 20 | Tue Aug 25, 12:14 | $2,104 |
| Oct 8 | Mon Oct 12, 10:09 | $1,991 (then the banked reset) |
| Oct 15 | Wed Oct 21, 18:00 | $1,883 |
| Oct 22 | Thu Oct 29, 02:00 | $2,054 |

Next to nothing ran between a weekly hit and the next reset, Fable included: $17 and $11 in
the two summer windows, $0 in the two October ones.

## The near-full weeks

The operator aims at 98–99 % of the quota a week, so a week with no free reset counts even
without a hit.

| | Weeks | Mean | Median | Range | Spread |
|---|---|---|---|---|---|
| Before 2026-09-14 | Jul 2 – Aug 20 (8) | $2,023 | $2,062 | $1,763–2,165 | ±6 % |
| After | Sep 17 – Oct 29 (6) | $1,897 | $1,895 | $1,798–2,054 | ±5 % |

The two outliers of the raw weekly sums are reset weeks: Jun 18 at $2,713, with the Jun 19–20
reset, and Sep 3 at $2,518, with the Sep 4 reset.

## The 2026-09-14 change

The change took the operator's plan from +50 % over the original quota to +25 %. That is
−16.7 %. The near-full weeks show **−6.2 % by the mean and −8.1 % by the median.**

The weeks after the change are on a different model. Opus 5.5 replaced 5.1 on 2026-09-22, and our
table prices 5.5 below 5.1. Holding the model fixed:

- **The 5.1 weeks before the change** (Jul 23 – Aug 20, five weeks) average $2,046.
- **The one 5.1 week after it** (Sep 17) came to $1,798. That is **−12 %**.
- **The 5.5 weeks after it** average $1,917, 7 % above that 5.1 week.

That is the shape a −12 to −17 % cut would leave if the quota counts Opus 5.5 7–14 % lighter,
relative to 5.1, than `PRICES` does. It rests on one week, so it is weak.

claude.ai does not explain the gap in the direction it was first guessed. A larger claude.ai
share now than in summer makes the measured drop *bigger*, not smaller. For claude.ai alone to
explain it, its share would have had to be about 17 % in summer against 5 % now.

## The 2026-05-13 increase

The +50 % of 2026-05-13 cannot be seen. No weekly or 5-hour limit was hit before it, and weeks
ran $600–900 apart from Apr 9 ($1,685) and Apr 16 ($1,235, a reset week).

Apr 9 does not fit the later line. It spent $1,685 on Opus 4.6 without a hit. After +50 % that
implies a quota of at least $2,500, and no later week came near it. Either the quota counted Opus
4.6 lighter than its list price, or the quota per dollar shrank between April and July.

## What it says about our prices

- **The weekly sums are consistent.** That is the check this read was asked for.
- **The 5.5 price cut is real in the quota.** Re-priced at the 5.1 rates, the 5.5 weeks would come
  to $2,900–3,600, some 50 % over the weeks before a cut. So `PRICES` is right to price 5.5 below
  5.1.
- **By how much is open.** The residual is 7–14 %, within the noise of one week and an unknown
  claude.ai share. A cost comparison across the 5.1 → 5.5 switch carries that slack, for example
  `model-effort-read-2026-10-03.md`'s "5.1 → 5.5 halves $/line".

## Next

The operator collects the usage endpoint's readings from 2026-11-05. A few weeks of them give
cost per percent of the quota directly, week by week, with claude.ai inside the percentage.
Fitted per model, they answer the 5.5-versus-5.1 question this read can only bound.

## Reproduce

The data is `docs/research/data/quota-2026-11-05.json`: cost per UTC hour and model family,
tokens per quota week and model, and every limit message. It holds no message content. The
scan takes about ten minutes on six workers.

```
python3 docs/research/tools/quota_readout.py scan --since 2026-01-01   # rewrites the data file
python3 docs/research/tools/quota_readout.py weeks
python3 docs/research/tools/quota_readout.py hits
python3 docs/research/tools/quota_readout.py compare
```
