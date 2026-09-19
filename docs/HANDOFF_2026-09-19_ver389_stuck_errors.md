# Handoff: VER-389, snippets stranded in `Error` (as of 2026-09-19 19:20 UTC)

Written by Claude Code (session `claude/verdad-accuracy-hallucination-xn7kgv`) for the Claude Code
instance that will execute this. **Your job is to apply three SQL steps to production and verify
them.** Everything is already written, dry-run verified and committed. Nothing has been applied.

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
| of those, tagged `Election Integrity` | 102 |
| Stage 3 throughput | ~155/hour (~3,700/day), live queue shallow |
| Stage 4 throughput | ~254/day observed peak (09-10..14); now 50-80/day, `Ready for review` empty |

Eligible `Error` rows by recording month (`skipped_backlog` is excluded by the sweeper):

| Month | Error rows | `skipped_backlog` | eligible |
|---|---|---|---|
| 2026-06 | 49,173 | 19,886 | 28,076 |
| 2026-07 | 48,866 | 11,480 | 34,953 |
| 2026-08 | 52,060 | 17,272 | 32,765 |
| 2026-09 | 7,744 | 566 | 5,909 |

Failure modes among the 3,932 stuck 95+ rows since Aug 1: 2,250 `503 UNAVAILABLE`, 1,231 other
Stage 4, 442 `429` quota, 9 other.

**Stage 4 is the binding constraint.** At ~254/day the full 2,837 is roughly two weeks. That is why
the runbook releases in priority order instead of all at once.

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
(committed as `79eff43` on branch `claude/verdad-accuracy-hallucination-xn7kgv`).

Paste each step separately into the Supabase SQL editor, in order, checking the inline
verification query before moving on. Per `.claude/rules/supabase-sql.md`, migrations and loose SQL
in this repo are applied by hand; do not use `supabase db push`.

**Step 1** moves `3e53d8e1` to `Ready for review`. One row. Watch it complete end to end
(`reviewed_at` becomes non-NULL, `status` becomes `Processed`) before releasing the batch. At
current review rates this should be minutes, not hours.

**Step 2** moves the 102 election-tagged 95+ rows. Dry-run verified read-only: **101** to
`Ready for review`, **1** to `New`. Expect it to clear inside a day.

**Step 3** schedules the sweeper: `cron.schedule('sweep-retryable-errors', '15 * * * *',
$$SELECT public.sweep_retryable_errors(6)$$)`. Batch 6 hourly is ~144/day, sized to stay under the
observed Stage 4 peak while leaving headroom for live recordings.

Step 1's row is inside step 2's set. Running step 1 first is safe: step 2 only touches rows still
in `Error`, so the row is not picked up twice and `analysis_attempts` stays at 1.

### After applying

1. Confirm `3e53d8e1` reaches `Processed` and is **not** in `user_hide_snippets`. If it is hidden,
   check `snippet_quarantine_log` for which batch caught it before assuming a bug.
2. Re-run Carlos's search and report the newest result date:
   `get_snippets('spanish', '{}', 0, 10, 'latest', 'fulton', true)`.
3. Watch `cron.job_run_details` for the first sweeper firing, then watch Stage 4 throughput for a
   few hours. **If Stage 4 throughput stays at or below ~254/day, `p_batch` can be raised.** If the
   `Ready for review` queue grows without draining, lower it or unschedule.
4. Post results to `#verdad` thread `1789491342.759259` and comment on VER-389.

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

- **VER-388 (open):** the Stage 4 review evidence gate is **not** capping absence-of-evidence
  verdicts. Two snippets were re-scored 98 and 100 on 2026-09-18 with zero contradicting URLs in
  their Stage 3 record. Re-queued rows go back through Stage 4, so **a score can come back
  different**. For `3e53d8e1` the 95 should hold: it claims a Supreme Court mail-in ruling on
  2026-09-10, four days before the real USPS v. California order of 2026-09-14. Do not promise
  Carlos a specific score before it completes.
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
