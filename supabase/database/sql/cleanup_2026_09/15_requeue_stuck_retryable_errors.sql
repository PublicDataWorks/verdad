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
--   of those, tagged Election Integrity : 102
--   Stage 3 throughput  : ~155/hour (~3,700/day), live queue shallow
--   Stage 4 throughput  : ~254/day observed peak (2026-09-10..14); at the time of writing
--                         50-80/day, demand-limited with an effectively empty review queue
--
-- Stage 4 capacity is the binding constraint: the full 2,837 would take ~2 weeks to review.
-- Carlos Chirinos (palabra) publishes the first VERDAD-sourced story next week, so this file
-- re-queues in priority order instead of all at once.
--
-- ============================================================================================
-- How to run
-- ============================================================================================
-- Paste each step separately in the Supabase SQL editor and check its verification query
-- before moving on. Steps 0 to 2 are ordinary DDL/DML in explicit transactions. Step 3
-- schedules a cron job and can be undone with cron.unschedule.
--
-- Steps 1 and 2 record every row they touch in public.snippet_requeue_log (step 0). That log
-- is what makes verification and rollback exact: once step 3 is running, the sweeper also sets
-- analysis_attempts = 1 on rows of its own, so any predicate keyed on analysis_attempts alone
-- would sweep up unrelated work. Always scope to the log.

-- --------------------------------------------------------------------------------------------
-- Step 0: audit log, so steps 1 and 2 are reversible and verifiable by exact row set.
-- --------------------------------------------------------------------------------------------
-- Same shape and intent as public.snippet_quarantine_log (02_create_snippet_quarantine_log.sql):
-- no FK on snippet on purpose, so the log survives independently of the rows it describes.

BEGIN;

CREATE TABLE IF NOT EXISTS public.snippet_requeue_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    snippet         UUID NOT NULL,
    previous_status public.processing_status NOT NULL,
    previous_error  TEXT,
    new_status      public.processing_status NOT NULL,
    batch           TEXT NOT NULL,
    requeued_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (snippet, batch)
);

COMMENT ON TABLE public.snippet_requeue_log IS
    'VER-389: which snippets were moved out of Error by the 15_requeue runbook, from what, to what, and in which batch. Rollback and verification join to this table.';

CREATE INDEX IF NOT EXISTS idx_snippet_requeue_log_batch
    ON public.snippet_requeue_log (batch);

ALTER TABLE public.snippet_requeue_log ENABLE ROW LEVEL SECURITY;
GRANT ALL ON TABLE public.snippet_requeue_log TO service_role;

COMMIT;

-- Verify: SELECT to_regclass('public.snippet_requeue_log');  -- not null

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
--
-- The guards below mirror sweep_retryable_errors() so that re-running this step after a second
-- failure cannot push the row past the retry ceiling or re-queue a non-transient failure.

BEGIN;

WITH picked AS (
    SELECT id, status, error_message
    FROM public.snippets
    WHERE id = '3e53d8e1-fdbd-4c4c-a692-f34be0b10962'
      AND status = 'Error'
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
    FOR UPDATE
),
moved AS (
    UPDATE public.snippets s
    SET status            = CASE WHEN p.error_message LIKE '[Stage 4]%'
                                 THEN 'Ready for review'::public.processing_status
                                 ELSE 'New'::public.processing_status END,
        error_message     = NULL,
        analysis_attempts = s.analysis_attempts + 1
    FROM picked p
    WHERE s.id = p.id
    RETURNING s.id, p.status AS previous_status, p.error_message AS previous_error, s.status AS new_status
)
INSERT INTO public.snippet_requeue_log (snippet, previous_status, previous_error, new_status, batch)
SELECT id, previous_status, previous_error, new_status, 'requeue-2026-09-19-ver389-step1' FROM moved
ON CONFLICT (snippet, batch) DO UPDATE
    SET previous_status = EXCLUDED.previous_status,
        previous_error  = EXCLUDED.previous_error,
        new_status      = EXCLUDED.new_status,
        requeued_at     = now();

COMMIT;

-- Verify: exactly one logged row, and the snippet now Ready for review with attempts = 1.
--   SELECT l.snippet, l.previous_status, l.new_status, s.status, s.analysis_attempts,
--          s.error_message, (s.confidence_scores->>'overall') AS score
--   FROM public.snippet_requeue_log l
--   JOIN public.snippets s ON s.id = l.snippet
--   WHERE l.batch = 'requeue-2026-09-19-ver389-step1';
--
-- If it returns no rows, the guards rejected it: check why before forcing anything.
--   SELECT id, status, analysis_attempts, error_message FROM public.snippets
--   WHERE id = '3e53d8e1-fdbd-4c4c-a692-f34be0b10962';
--
-- Then watch it clear (reviewed_at becomes non-NULL, status becomes 'Processed'):
--   SELECT id, status, reviewed_at, (confidence_scores->>'overall') AS score
--   FROM public.snippets WHERE id = '3e53d8e1-fdbd-4c4c-a692-f34be0b10962';
-- And confirm it is actually visible, i.e. not hidden by an earlier cleanup batch:
--   SELECT * FROM public.user_hide_snippets
--   WHERE snippet = '3e53d8e1-fdbd-4c4c-a692-f34be0b10962';

-- --------------------------------------------------------------------------------------------
-- Step 2: the 102 election-tagged snippets scoring 95+ stranded since 2026-08-01.
-- --------------------------------------------------------------------------------------------
-- This is the set that decides what an elections reporter sees. At ~254/day of Stage 4 capacity
-- it clears well inside a day. The predicate mirrors sweep_retryable_errors() exactly, including
-- the analysis_attempts < 3 ceiling and the excluded 'skipped_backlog' / 'Intentionally Hidden'
-- markers, so this file and the sweeper can never fight over the same row.

BEGIN;

WITH picked AS (
    SELECT id, status, error_message
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
),
moved AS (
    UPDATE public.snippets s
    SET status            = CASE WHEN p.error_message LIKE '[Stage 4]%'
                                 THEN 'Ready for review'::public.processing_status
                                 ELSE 'New'::public.processing_status END,
        error_message     = NULL,
        analysis_attempts = s.analysis_attempts + 1
    FROM picked p
    WHERE s.id = p.id
    RETURNING s.id, p.status AS previous_status, p.error_message AS previous_error, s.status AS new_status
)
INSERT INTO public.snippet_requeue_log (snippet, previous_status, previous_error, new_status, batch)
SELECT id, previous_status, previous_error, new_status, 'requeue-2026-09-19-ver389-step2' FROM moved
ON CONFLICT (snippet, batch) DO UPDATE
    SET previous_status = EXCLUDED.previous_status,
        previous_error  = EXCLUDED.previous_error,
        new_status      = EXCLUDED.new_status,
        requeued_at     = now();

COMMIT;

-- Verify against the log, not against analysis_attempts: once step 3 is running the sweeper
-- also produces rows with analysis_attempts = 1, and they are not ours.
-- Expect ~102 rows total (~101 to 'Ready for review', ~1 to 'New'); step 1's row is already
-- out of Error by now, so it is logged under step1 and not repeated here.
--   SELECT l.new_status, count(*)
--   FROM public.snippet_requeue_log l
--   WHERE l.batch = 'requeue-2026-09-19-ver389-step2'
--   GROUP BY 1;
--
-- Nothing eligible left behind (same predicate as the step, so a non-zero result means rows
-- that genuinely still qualify, not rows the guards excluded on purpose):
--   SELECT count(*) AS still_eligible FROM public.snippets
--   WHERE status = 'Error'
--     AND recorded_at >= '2026-08-01'
--     AND (confidence_scores->>'overall')::integer >= 95
--     AND confidence_scores::text ILIKE '%Election Integrity%'
--     AND analysis_attempts < 3
--     AND error_message IS NOT NULL
--     AND error_message NOT LIKE 'skipped_backlog%'
--     AND error_message <> 'Intentionally Hidden'
--     AND (error_message LIKE 'KeyError%' OR error_message LIKE '%503%'
--       OR error_message LIKE '%UNAVAILABLE%' OR error_message LIKE '%429%'
--       OR error_message LIKE '%RESOURCE_EXHAUSTED%'
--       OR error_message LIKE '%No response from Gemini%'
--       OR error_message LIKE '%500 Internal error%'
--       OR error_message LIKE '%temporarily unavailable%'
--       OR error_message LIKE '%Failed to create MCP session%');
--
-- Progress of the batch through review:
--   SELECT s.status, count(*) FROM public.snippet_requeue_log l
--   JOIN public.snippets s ON s.id = l.snippet
--   WHERE l.batch = 'requeue-2026-09-19-ver389-step2' GROUP BY 1;

-- --------------------------------------------------------------------------------------------
-- Step 3: schedule the sweeper for the long tail.
-- --------------------------------------------------------------------------------------------
-- Sizing: Stage 4 is the constraint at ~254/day observed peak, against demand of 50-80/day at
-- the time of writing. A batch of 6 every hour adds ~144/day, which keeps the combined load
-- under the observed peak and leaves headroom for live recordings. Raise p_batch only after
-- watching a few hours of Stage 4 throughput; the sweeper already orders by recorded_at DESC,
-- so newest content drains first either way.
--
-- Do NOT jump straight to a large batch: ~101,700 rows are eligible and re-queueing them at
-- once would swamp both the review queue and the Gemini quota.
--
-- Note the sweeper does NOT write to snippet_requeue_log. That is deliberate: the log exists to
-- delimit what this runbook did by hand, so that the rollback below can never touch the
-- sweeper's rows.

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
-- Rolling steps 1 and 2 back (only if a re-queue turns out to be wrong)
-- ============================================================================================
-- Scoped to the exact rows this runbook moved, via the log. Do not substitute a predicate on
-- analysis_attempts: after step 3 the sweeper produces rows that look identical by that measure
-- and reverting them would push unrelated pending work back into Error.
--
--   BEGIN;
--   UPDATE public.snippets s
--   SET status        = 'Error'::public.processing_status,
--       error_message = '[manual] reverted VER-389 re-queue'
--   FROM public.snippet_requeue_log l
--   WHERE s.id = l.snippet
--     AND l.batch IN ('requeue-2026-09-19-ver389-step1', 'requeue-2026-09-19-ver389-step2')
--     AND s.status IN ('New', 'Ready for review')
--     AND s.reviewed_at IS NULL;
--   COMMIT;
--
-- Restrict to one step by naming a single batch. This only makes sense before the rows are
-- picked up; once analysis completes they are ordinary Processed rows and reverting them is
-- meaningless, which is what the status and reviewed_at conditions enforce.
