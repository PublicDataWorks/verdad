# Handoff: VER-389, snippets stranded in `Error` (as of 2026-09-19 19:20 UTC)

Written by Claude Code (session `claude/verdad-accuracy-hallucination-xn7kgv`) for the Claude Code
instance that will execute this. **Your job is to apply steps 0, 2 and 3 of the runbook to
production and verify them.** Everything is already written, dry-run verified and committed.
Nothing has been applied (updated 2026-09-21 by Thien after review; step 1 is closed).

Rajiv Sinclair (technical PM, `rajiv@publicdata.works`) owns product decisions and has asked for
this to be done immediately without waiting for Thien Lam (engineer, East Agile, owns deploys,
on VERDAD until 2026-10-02). Coordination: Linear team VERDAD (source of truth for other agents),
Slack `#verdad` (`C07JYU3729G`), GitHub `PublicDataWorks/verdad`. Keep all three updated.

## 1. Why this is urgent

Carlos Chirinos is a reporter at **palabra** (NAHJ) writing the **first published story sourced
from VERDAD**, on Fulton County, Georgia election-fraud narratives. He publishes **next week**.
Tamoa Calzadilla (NAHJ editor) relayed his message on 2026-09-19:

> "between last night and this morning I've been searching the app and I can't find anything about
> Fulton. The only thing that comes up is a piece from early September about election fraud, but
> it's about an alleged law that Newsom signed in California. I also notice that there haven't been
> any major news developments about Fulton and the FBI investigation since July, on top of the
> Maduro situation."

He is right, and the cause is not search.

## 2. Root cause

`public.sweep_retryable_errors(p_batch, p_max_attempts)` was applied to production on 2026-09-18
(`supabase/migrations/20260918030000_sweep_retryable_errors.sql`, VER-382). Its logic is correct:
it picks `status = 'Error'` rows whose `error_message` matches a transient-failure pattern (503,
UNAVAILABLE, 429, RESOURCE_EXHAUSTED, KeyError, no-response, MCP session), resets them to `New` or
`Ready for review` depending on which stage failed, and increments `analysis_attempts`.

**It was never added to `cron.job`.** The only active jobs are:

| jobid | schedule | command |
|---|---|---|
| 7 | `* * * * *` | `run_tsv_backfill()` |
| 9 | `5 * * * *` | `sweep_stuck_snippets()` |

`sweep_stuck_snippets` rescues rows stuck mid-flight in `Processing` / `Reviewing`. **Nothing
rescues rows that landed in `Error`.** Proof it has never run: `analysis_attempts = 0` on all
275,914 `Error` rows, without a single exception.

Thien's retry-on-transient-error fix (deployed Mon 2026-09-14) did largely stop *new* losses:
weekly arrivals of stuck 95+ rows fell from 722 (week of 09-07) to 175 (week of 09-14). The
*existing* bucket was never drained.

## 3. Measurements (read-only, production, 2026-09-19)

| Signal | Value |
|---|---|
| Total rows in `Error` | 275,914 |
| Sweeper-eligible since June | ~101,700 |
| of those, scoring 95+ and recorded since 2026-08-01 | 2,837 |
| of those, tagged `Election Integrity` | 101 on 2026-09-21 (102 on 09-19, before `3e53d8e1` left `Error`) |
| Stage 3 throughput | 2,800-3,700/day (2026-09-21: `New` queue ~3,700 deep; ~40% slower 00:00-07:00 UTC on the Gemini free-tier daily cap) |
| Stage 4 throughput | 46-178/day over 14-20 Sep; no reviews complete 00:00-07:00 UTC |

Eligible `Error` rows by recording month (`skipped_backlog` is excluded by the sweeper):

| Month | Error rows | `skipped_backlog` | eligible |
|---|---|---|---|
| 2026-06 | 49,173 | 19,886 | 28,076 |
| 2026-07 | 48,866 | 11,480 | 34,953 |
| 2026-08 | 52,060 | 17,272 | 32,765 |
| 2026-09 | 7,744 | 566 | 5,909 |

Failure modes among the 3,932 stuck 95+ rows since Aug 1: 2,250 `503 UNAVAILABLE`, 1,231 other
Stage 4, 442 `429` quota, 9 other.

91% of the eligible tail routes to `New`, so **Stage 3 is the binding constraint** for the drain;
Stage 4 only sees the 95+ fraction. That is why the runbook releases in priority order instead of
all at once.

## 4. Carlos's specific snippet

`3e53d8e1-fdbd-4c4c-a692-f34be0b10962`

- Recorded 2026-09-10 07:27 UTC, Radio Mundo, Florida.
- Stage 3 scored it **95** with a correct debunk. Title: "False Claims of a Supreme Court Decision
  to Overturn Mail-in Voting Laws".
- Stage 4 failed with `503 UNAVAILABLE` at 07:51 UTC. It has been in `Error` ever since.
- Transcript contains exactly the Fulton-plus-Maduro pairing Carlos describes: *"Ahí están los
  resultados del condado de Fulton. Incluso el reconocimiento la semana pasada del condado de
  Fulton de todo lo que violaron. En Georgia se violaron 1.7 millones de votos... cuando esté
  declarando Nicolás Maduro va a estar Gretchen Whitmer y Jocelyn Benson de Michigan."*

Note the content is Spanish, so it says *"condado de Fulton"*, not "Fulton County". A literal
search for `fulton county` returns 0 rows; `fulton` returns it fine.

## 5. What search actually does (do not "fix" search)

Reproduced in production: `get_snippets('spanish', '{}', 0, 10, 'latest', 'fulton', true)` returns
**40 results, correctly ranked**, and the top hits are genuinely about Fulton County election
fraud. The newest is **2026-07-24**; the rest are April and March. Search is healthy. The gap after
July is the `Error` backlog, nothing else.

The piece Carlos saw is `92bd7c73` (2026-09-09, score 95, "False Claims About a Nonexistent Law
(AB 2624) and Election Fraud in California"). It is a correct flag; it surfaced because it is one
of the few election items that completed.

## 6. Your task

Apply `supabase/database/sql/cleanup_2026_09/15_requeue_stuck_retryable_errors.sql`
(branch `claude/ver-389-requeue-stuck-errors`, PR #118).

**Status as of 2026-09-21 (Thien):** step 1 is closed and must not be re-run. An earlier revision
re-queued `3e53d8e1` on 2026-09-19; Stage 4 capped it to 40; it was then restored to `Processed`
95 by hand with a regrounded explanation (batch `unmask-2026-09-19-carlos`, PR #120/#121), together
with `fb43bf56` and `c253e70f`. Re-queueing any of the three would overwrite that text.
**Steps 0 and 2 were applied 2026-09-21 08:33-08:34 UTC** (105 rows to `New`, batch
`requeue-2026-09-21-ver389-step2`, pre-run snapshot kept by Thien). Step 3 is not scheduled yet:
run it after a day of step 2 yield.

Paste each step separately into the Supabase SQL editor, in order, checking the inline
verification query before moving on. Per `.claude/rules/supabase-sql.md`, migrations and loose SQL
in this repo are applied by hand; do not use `supabase db push`.

**Step 0** creates `public.snippet_requeue_log`, same shape and intent as the existing
`snippet_quarantine_log`. Steps 1 and 2 record every row they touch in it. **This is what makes
rollback safe:** once step 3 is running, `sweep_retryable_errors()` also sets
`analysis_attempts = 1` on rows of its own, so any rollback keyed on `analysis_attempts` alone
would drag unrelated pending work back into `Error`. Always scope to the log.

**Step 1** is done (see the status above); the file keeps a note in its place.

**Step 2** moves the election-tagged 95+ rows plus the four hand-held Fulton rows, all to `New`
(section 8 says why not `Ready for review`). Dry run read-only 2026-09-21: **105** rows, batch
`requeue-2026-09-21-ver389-step2`. Stage 3 polls newest-first and its `New` queue on 2026-09-21
is ~3,700 rows recorded 2-5 Sep (live recordings are processed within hours), so step-2 rows
recorded after 5 Sep run almost at once and the August ones wait until that backlog drains,
about a week at the current ~500/day net. Applied 2026-09-21 on Thien's call (section 8 has the
19 Sep hold request and why it no longer applies).

**Step 3** schedules the sweeper: `cron.schedule('sweep_retryable_errors', '15 8-23 * * *',
$$SELECT public.sweep_retryable_errors(50)$$)`. 91% of the eligible tail routes to `New`, so Stage 3
is the constraint; 50/hour outside the Gemini quota dead window (00:00-07:00 UTC) is ~800/day, about
a quarter on top of live work. The sweeper deliberately does **not** write to `snippet_requeue_log`.

**Verify against the log, not against `analysis_attempts`.** The runbook's verification queries
already do this; if you write your own, do the same.

### After applying

1. Run the yield query at the end of step 2 after a day or two: how many came back `Processed` at
   95+ vs capped vs `Error` again. Spot-check the 95+ ones against their sources before anyone
   tells a reporter they are back.
2. Watch `cron.job_run_details` for the first sweeper firing, then Stage 3 throughput and the `New`
   queue depth for a day. If the queue grows without draining, lower `p_batch` or unschedule.
3. Post results to `#verdad` thread `1789491342.759259` and comment on VER-389.

## 7. Constraints you must respect

- **Do not raise `p_batch` aggressively.** ~101,700 rows are eligible. Releasing them at once would
  swamp the review queue and the Gemini quota. The sweeper orders by `recorded_at DESC`, so newest
  content drains first regardless of batch size; patience costs nothing.
- **Do not touch the `skipped_backlog` rows.** They are excluded deliberately.
- Per `AGENTS.md`: never `fly deploy`, never run migrations beyond what is asked, never write to
  production data beyond this runbook without Rajiv's explicit go. This handoff is that go, for
  these three steps only.
- Run `make check` before any commit. Do not lower the coverage gate.

## 8. Known interactions

- **Why step 2 routes everything to `New` (settled 2026-09-21, pending Rajiv's go).** A
  `[Stage 4]` failure re-queued to `Ready for review` is re-judged on the Stage 3 evidence already
  in `grounding_metadata`; `apply_evidence_caps` caps a `verified_false` verdict at 40 unless that
  record holds a `contradicts_claim` article URL not marked `url_observed_in_tools = false`. The
  2026-09-19 count "0 of 101 hold one" looked under a `verification_evidence` key that does not
  exist (the evidence is top-level, `searches_performed`); measured there, **34 of 101** do. But all
  34 predate the tool record (PR #98) so `url_observed_in_tools` is unset, and the URLs are mostly
  PolitiFact / FactCheck / Snopes / AP links of the kind the VER-391 audit found 85-90% dead: Stage 4
  would restore 95 on unverifiable citations. So `Ready for review` is wrong for both halves, and
  `New` (full Stage 3 re-run: search fixed by VER-390, only tool-returned URLs count, Stage 4 tool
  record and KB validation from PR #125) is the only route where a 95 means something.
  `3e53d8e1`, `717925c8` and `0759b76b` capping to 40 on re-review were the gate working as
  designed. **Rajiv's sessions (VER-389 comment 19 Sep 20:22 UTC, Slack 22:50 UTC) asked to hold
  the whole set** until the pipeline cannot call a true post-cutoff event false on model knowledge
  alone (VER-391 item 4, not built), with a hand-audited allowlist as the only release path. That
  was argued against the pre-VER-390/391 pipeline; under today's gates a re-run reaches 95 only on
  a tool-returned article, the same bar live rows meet, and the residual misread-article risk is
  the pipeline's normal risk. Rajiv decides whether that is enough.
- **Since 2026-09-21 Stage 4 also stores a tool record and a citation check (PR #125/#126, worker
  v256).** Capping on invented URLs is off for now (`CITATION_CHECK_CAPS = False`), so it changes
  nothing here yet; when it is turned on it is a second 40-cap path for re-reviewed rows.
- **Four Fulton rows were parked by hand outside every pattern:** `a09b0842`, `b8f8e3ea`,
  `961d43c5`, `2dc8cf14` carry `error_message = '[manual] held VER-389 re-queue: ...'` with
  `analysis_attempts = 1` (set 2026-09-19 by a session that stopped short of re-queueing them to
  `Ready for review`). The sweeper never matches that marker; step 2 picks them up by id and routes
  them to `New` with the rest.
- **VER-358 (open, Rajiv's decision):** the feed shows only `overall >= 95`. Fulton and fraud
  *narratives* (a host asserting fraud with no checkable claim) score below 50 by design and stay
  invisible whatever this fix does. 61 Fulton mentions Aug+Sep, 0 at 95+, 48 below 50.
- **VER-387 / PR #117 (open, green):** denormalizes `location_state` onto `snippets`. Unrelated to
  this, but do not apply it before Carlos publishes; see its own README for sequencing.
- **VER-374:** most stations are in Florida, only three in Georgia. Even with this fixed, Fulton
  coverage is thin. Adding Georgia stations is the durable answer.

## 9. Trap to avoid

Searching `fulton` in the transcript matches **Fulton Bank** (a radio sponsor, ~6 rows) and
**Fulton Sheen** (a Catholic bishop, dozens of rows). Exclude `%sheen%` and check for `condado de
Fulton` when counting genuine Fulton County coverage. Since Aug 1 there is exactly **one** genuine
Fulton County election item, and it is `3e53d8e1`.
