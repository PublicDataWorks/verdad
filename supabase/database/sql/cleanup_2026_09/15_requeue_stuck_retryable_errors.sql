-- Re-queue snippets stranded in status 'Error' by transient provider failures (VER-389).
--
-- ============================================================================================
-- Why
-- ============================================================================================
-- public.sweep_retryable_errors() was created in production on 2026-09-18
-- (supabase/migrations/20260918030000_sweep_retryable_errors.sql, VER-382) but was never added
-- to cron.job. The only scheduled jobs are run_tsv_backfill (every minute) and
-- sweep_stuck_snippets (hourly at :05); the latter rescues rows stuck mid-flight in
-- Processing / Reviewing, and nothing rescues rows that landed in Error. Confirmed never run:
-- analysis_attempts = 0 on all 275,914 Error rows as of 2026-09-19.
--
-- Measured on production 2026-09-19 (read-only):
--   sweeper-eligible Error rows since June : ~101,700
--   of those, scoring 95+ and recorded since 2026-08-01 : 2,837
--   of those 2,837, tagged Election Integrity : 102
--   Stage 3 throughput  : ~155/hour (~3,700/day), live queue shallow
--   Stage 4 throughput  : ~254/day observed peak (2026-09-10..14); currently 50-80/day,
--                         demand-limited with an empty 'Ready for review' queue
--
-- Stage 4 capacity is the binding constraint: the full 2,837 would take ~2 weeks to review.
-- Carlos Chirinos (palabra) publishes the first VERDAD-sourced story next week, so this file
-- re-queues in priority order instead of all at once.
--
-- ============================================================================================
-- How to run
-- ============================================================================================
-- Paste each step separately in the Supabase SQL editor and check its verification query
-- before moving on. Steps 1 and 2 are ordinary DML in explicit transactions. Step 3 schedules
-- a cron job and can be undone with cron.unschedule.
--
-- Rollback for steps 1 and 2: the rows return to Error on their own if analysis fails again.
-- To force them back by hand, see the note at the bottom of this file.

-- --------------------------------------------------------------------------------------------
-- Step 1: the single Fulton County snippet Carlos Chirinos is looking for.
-- --------------------------------------------------------------------------------------------
-- Recorded 2026-09-10 07:27 UTC on Radio Mundo (Florida), scored 95 by Stage 3 with a correct
-- debunk, then Stage 4 died on '503 UNAVAILABLE' at 07:51 UTC and it has sat in Error since.
-- Transcript: "Ahi estan los resultados del condado de Fulton. Incluso el reconocimiento la
-- semana pasada del condado de Fulton de todo lo que violaron. En Georgia se violaron 1.7
-- millones de votos... cuando este declarando Nicolas Maduro va a estar Gretchen Whitmer y
-- Jocelyn Benson de Michigan."
-- Error came from Stage 4, so it goes back to 'Ready for review', not 'New'.
--
-- This row is also inside step 2's set (it is Election Integrity tagged and scores 95). Step 1
-- exists so you can move one row, watch it complete end to end, and only then release the batch.
-- Running step 1 first is safe: it leaves the row in 'Ready for review', and step 2 only touches
-- rows still in 'Error', so the row is not picked up twice and analysis_attempts stays at 1.

BEGIN;

UPDATE public.snippets
SET status            = 'Ready for review'::public.processing_status,
    error_message     = NULL,
    analysis_attempts = analysis_attempts + 1
WHERE id = '3e53d8e1-fdbd-4c4c-a692-f34be0b10962'
  AND status = 'Error';

COMMIT;

-- Verify: one row, status 'Ready for review', analysis_attempts 1, error_message NULL.
--   SELECT id, status, analysis_attempts, error_message,
--          (confidence_scores->>'overall') AS score
--   FROM public.snippets WHERE id = '3e53d8e1-fdbd-4c4c-a692-f34be0b10962';
-- Then watch for it to clear (reviewed_at becomes non-NULL, status becomes 'Processed'):
--   SELECT id, status, reviewed_at, (confidence_scores->>'overall') AS score
--   FROM public.snippets WHERE id = '3e53d8e1-fdbd-4c4c-a692-f34be0b10962';

-- --------------------------------------------------------------------------------------------
-- Step 2: the 102 election-tagged snippets scoring 95+ stranded since 2026-08-01.
-- --------------------------------------------------------------------------------------------
-- This is the set that decides what an elections reporter sees. At ~254/day of Stage 4 capacity
-- it clears well inside a day. The predicate mirrors sweep_retryable_errors() exactly, including
-- the analysis_attempts < 3 ceiling and the excluded 'skipped_backlog' / 'Intentionally Hidden'
-- markers, so this file and the sweeper can never fight over the same row.

BEGIN;

WITH picked AS (
    SELECT id, error_message
    FROM public.snippets
    WHERE status = 'Error'
      AND recorded_at >= '2026-08-01'
      AND (confidence_scores->>'overall')::integer >= 95
      AND confidence_scores::text ILIKE '%Election Integrity%'
      AND analysis_attempts < 3
      AND error_message IS NOT NULL
      AND error_message NOT LIKE 'skipped_backlog%'
      AND error_message <> 'Intentionally Hidden'
      AND (
            error_message LIKE 'KeyError%'
         OR error_message LIKE '%503%'
         OR error_message LIKE '%UNAVAILABLE%'
         OR error_message LIKE '%429%'
         OR error_message LIKE '%RESOURCE_EXHAUSTED%'
         OR error_message LIKE '%No response from Gemini%'
         OR error_message LIKE '%500 Internal error%'
         OR error_message LIKE '%temporarily unavailable%'
         OR error_message LIKE '%Failed to create MCP session%'
      )
    ORDER BY recorded_at DESC
    FOR UPDATE SKIP LOCKED
)
UPDATE public.snippets s
SET status            = CASE WHEN p.error_message LIKE '[Stage 4]%'
                             THEN 'Ready for review'::public.processing_status
                             ELSE 'New'::public.processing_status END,
    error_message     = NULL,
    analysis_attempts = s.analysis_attempts + 1
FROM picked p
WHERE s.id = p.id;

COMMIT;

-- Verify: expect ~102 rows moved (101 to 'Ready for review', 1 to 'New').
--   SELECT status, count(*) FROM public.snippets
--   WHERE analysis_attempts = 1 AND recorded_at >= '2026-08-01'
--     AND confidence_scores::text ILIKE '%Election Integrity%'
--   GROUP BY 1;
-- And that none are left behind:
--   SELECT count(*) AS still_stuck FROM public.snippets
--   WHERE status = 'Error' AND recorded_at >= '2026-08-01'
--     AND (confidence_scores->>'overall')::integer >= 95
--     AND confidence_scores::text ILIKE '%Election Integrity%'
--     AND analysis_attempts < 3;

-- --------------------------------------------------------------------------------------------
-- Step 3: schedule the sweeper for the long tail.
-- --------------------------------------------------------------------------------------------
-- Sizing: Stage 4 is the constraint at ~254/day observed peak, against current demand of
-- 50-80/day. A batch of 6 every hour adds ~144/day, which keeps the combined load under the
-- observed peak and leaves headroom for live recordings. Raise p_batch only after watching a
-- few hours of Stage 4 throughput; the sweeper already orders by recorded_at DESC, so newest
-- content drains first either way.
--
-- Do NOT jump straight to a large batch: ~101,700 rows are eligible and re-queueing them at
-- once would swamp both the review queue and the Gemini quota.

SELECT cron.schedule(
    'sweep-retryable-errors',
    '15 * * * *',
    $$SELECT public.sweep_retryable_errors(6)$$
);

-- Verify the job exists and is active:
--   SELECT jobid, jobname, schedule, command, active FROM cron.job
--   WHERE jobname = 'sweep-retryable-errors';
-- After the first firing, check what it did:
--   SELECT jobid, status, return_message, start_time
--   FROM cron.job_run_details WHERE jobid =
--     (SELECT jobid FROM cron.job WHERE jobname = 'sweep-retryable-errors')
--   ORDER BY start_time DESC LIMIT 5;
-- Watch the backlog fall:
--   SELECT count(*) FROM public.snippets WHERE status = 'Error' AND analysis_attempts < 3;
--
-- Unschedule:  SELECT cron.unschedule('sweep-retryable-errors');

-- ============================================================================================
-- Forcing steps 1 and 2 back (only if a re-queue turns out to be wrong)
-- ============================================================================================
--   UPDATE public.snippets
--   SET status = 'Error', error_message = '[manual] reverted VER-389 re-queue'
--   WHERE analysis_attempts = 1 AND status IN ('New', 'Ready for review')
--     AND reviewed_at IS NULL;
-- Note this only makes sense before the rows are picked up; once analysis completes they are
-- ordinary Processed rows and reverting them is meaningless.
