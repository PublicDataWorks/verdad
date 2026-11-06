# VERDAD Stage 1 backlog re-queue plan (dry run)

Prepared 2026-11-02 04:40 UTC. Production was only read (SELECTs). SQL: `requeue_plan.sql`, same folder.

## Recommendation

1. Re-queue Tier A (8 stations, including SPMN, WZHF and XEMX) at the switch: 3,244 recordings, about $2.2k on phase 1.
2. Re-queue Tier B once Tier A's queue is empty.
3. Leave Tier C until after Nov 3.
4. Pause the pg_cron retry sweep while Tiers A and B drain.

The backlog is 22,259 recordings, not about 17,000: it grows by 2,431 a day. All of it costs about $5.3k on phase 1 or $7.6k on phase 2, and each day the switch waits adds about $570 (phase 1).

## Tiers

Shares are of Sep 26 to Oct 22 snippets.

- **Visible:** Processed with confidence of 95 or more, the feed's filter (839 snippets).
- **Election (all):** the election category at any confidence (829 snippets), as Sukari's doc counts it. Only 26 visible snippets carry the category.
- **US-focused:** my title keyword proxy for election snippets about US politics.

| Tier | Stations | Backlog | Per day | Backlog P1 / P2 | Daily P1 / P2 | Visible | Election (all) | Election (visible) | US-focused |
|---|---|---|---|---|---|---|---|---|---|
| A | WAXY, WNMA, WMUZ, WWFE, SPMN, WZHF, KHEM, XEMX | 3,244 | 350 | $2,170 / $2,370 | $236 / $257 | 42% | 67% | 81% (21) | 68% |
| B | WSUA, WADO, KVIV, XEKAM, WAQI, WKAQ, WSRF, KVNR, XEZOL | 3,668 | 400 | $900 / $1,270 | $98 / $139 | 40% | 23% | 15% (4) | 19% |
| C | the other 37 | 15,347 | 1,681 | $2,170 / $3,960 | $238 / $434 | 18% | 10% | 4% (1) | 13% |
| All | 54 | 22,259 | 2,431 | $5,250 / $7,610 | $572 / $830 | 100% | 100% | 100% (26) | 100% |

**Costs.** P1 is $0.017 per recording, plus $0.15 per flagged recording, plus $0.46 per Stage 3 clip. P2 is $0.15 per recording plus $0.46 per clip.

- I applied these per station, using last month's flag rate and clips per recording for each station, scaled so the network averages match the 18% flagged and 0.42 clips you gave. The raw history is 12.6% and 0.41.
- Clips run from 0.02 per recording (KCKO) to 4.4 (ARAB), and Stage 3 dominates the bill. That is why Tier A costs about the same on P1 and P2, while Tier C nearly doubles on P2.
- Check: Sukari's 12-station list scores 72% visible and 72% election here, matching the doc.

## Foreign stations

| Station | Election (all) | US-focused | Election (visible) | Tier | Daily P1 | Reason |
|---|---|---|---|---|---|---|
| SPMN (Russia) | 65 | 19 | 4 | **A** | $43 | Below |
| WZHF (Russia) | 49 | 22 | 2 | **A** | $59 | Below |
| XEMX (Mexico) | 8 | 7 | 0 | **A** | $3 | On the owner's list; cheap; its election content is about the US |
| XEKAM (Mexico) | 12 | 3 | 0 | B | $10 | Its yield is a Saturday health and religion show |
| XEZOL (Mexico) | 64 | 9 | 1 | B | $9 | Mostly Mexican politics |
| WKAQ (Puerto Rico) | 25 | 9 | 0 | B | $8 | Mostly PR party politics; PR's general election is in presidential years |

**SPMN and WZHF stay in Tier A, though the brief overstates them.**

- The 57 and 42 October election snippets are counted at any confidence. At the feed threshold the figures are 3 and 2.
- About 70% of SPMN's election items are about Ukraine, Brazil, Argentina, Haiti or Russia, not the US.
- Together they still carry 41 US-focused election items, the third-largest source after WAXY (93) and WNMA (60), and as many as WMUZ and KHEM combined. These are Russian state narratives about the midterms aimed at Spanish and Russian speakers in the US.
- They cost $102 a day on P1, 43% of Tier A, because they produce 1.8 to 2.6 clips per recording. If the budget binds, cut them first: Tier A drops to $134 a day and loses 6 of its 21 visible election snippets.

## Station-hour filtering

I ranked station-hours on Sep 26 to Oct 8 and scored them on Oct 9 to 22.

- **Tier B: no.** The top quarter of hours keeps 71% of visible snippets but only 48% of election snippets, at 41% of the P1 cost. That saves about $58 a day, and the hours it keeps are the supplement-ad slots on WSUA, WADO and WAQI.
- **Tier C: only on phase 2.** The top quarter of hours keeps 74% of visible and 82% of election snippets. That is 73% of the P1 cost (saving $64 a day) but 49% of the P2 cost (saving $220 a day). The samples are small: 82 visible and 51 election snippets.
- **ARAB** is Tier C's outlier: $102 a day on P1 for 3% of visible snippets. Release it last, or not at all.

## How the system behaves after a re-queue

1. **Stage 1 is already newest-first.** `fetch_a_new_audio_file_and_reserve_it()` (live definition checked) takes `New` rows by `recorded_at DESC`, so day slices are only useful as a budget gate.
   - New recordings from all 54 stations are always newer than the backlog, so they always run first.
   - Tiering therefore controls the backlog only. Going forward every station is processed, at $572 a day on P1.
2. **The pg_cron sweep `sweep_retryable_audio_errors(20)` runs at :25 and :55.** It re-queues the 20 newest 429 rows from the last 7 days, from all stations: about 960 a day, mostly Tier C, with no log rows. This is why retry_attempts is 0 or 1. Pause it (block 0b in the SQL) before Tier A goes, and re-enable it after Tier B drains.
3. **Tier B waits for Tier A to drain**, otherwise B's newer rows go ahead of A's. Block B refuses while more than 50 Tier A rows are still `New`.
4. **Throughput is inferred, not measured on the new pipeline.** Before the outage Stage 1 processed about 2,400 a day, matching intake, with peak hours of 150 to 178 recordings (about 4,000 a day).
   - If the new pipeline matches that, about 1,500 a day are left after live intake. Tier A then drains in about 2 days, A and B in about 4.5, and the whole backlog in about 14.
   - If capacity is tight, a migration can make the fetch function order by station tier and then by `recorded_at DESC`. That needs plan mode and approval.

## Cost of the first seven days after the switch

| Option | Phase 1 | Phase 2 |
|---|---|---|
| A+B backlog, live intake from all stations (recommended; no code change) | $7.1k | $9.5k |
| A+B backlog, live intake limited to A+B (needs the fetch-function migration) | $5.4k | $6.4k |
| Whole backlog plus all live intake | $9.3k | $13.4k |

## Runbook

1. Get approval, then pause the sweep.
2. Run Block A with COMMIT.
3. Watch monitor query (2) until Tier A's `queued_new` reaches 0.
4. Run Block B with COMMIT.
5. After Nov 3, decide on Tier C (phase 2, hour filter, no ARAB), then re-enable the sweep.

Each block logs prior state to `audio_requeue_log` (RLS on, no grants), checks picked = logged = now `New` and the pick size, and ends in ROLLBACK. The rollback block restores only rows still `New`.

## Caveats

- No write statement has been executed or syntax-tested (no local Postgres). The picks, both monitors and the function definitions were run read-only on production.
- Costs assume the new pipeline produces as many clips per recording as the old one. The Stage 3 cost per clip is the uncached figure.
