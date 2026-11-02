-- Drain the 95+ Error backlog with public.drain_error_backlog_95 (migration 20260924100000, VER-389).
--
-- 3,787 rows on 2026-09-24 (recorded 1 Aug to 15 Sep); the 23 Sep pilot of 50 brought 6 back at 95+.
-- 50 rows an hour outside the Gemini Pro dead window (00:00-07:00 UTC) is 800/day, ~5 days.
-- Start after the A2 re-check (VER-386) ends: both share the Stage 3 machine.
-- Do not schedule runbook 15 step 3 while this runs: the sweeper picks from the same pool, sends
-- '[Stage 4]' rows to 'Ready for review' and logs nothing.
-- Paste each step separately in the Supabase SQL editor.

-- --------------------------------------------------------------------------------------------
-- Step 0: dry run (read-only). Same predicate as the function's pick; keep them in sync.
-- --------------------------------------------------------------------------------------------

SELECT count(*) AS eligible, min(recorded_at)::date AS oldest, max(recorded_at)::date AS newest
FROM public.snippets s
WHERE s.status = 'Error'
  AND s.recorded_at >= '2026-08-01 00:00+00'
  AND (s.confidence_scores->>'overall')::integer >= 95
  AND s.analysis_attempts < 3
  AND coalesce(s.error_message, '') NOT LIKE 'skipped_backlog%'
  AND coalesce(s.error_message, '') <> 'Intentionally Hidden'
  AND NOT EXISTS (SELECT 1 FROM public.snippet_requeue_log l WHERE l.snippet = s.id);

-- --------------------------------------------------------------------------------------------
-- Step 1: smoke test after the migration is applied. Returns {"batch": ..., "requeued": 1}.
-- --------------------------------------------------------------------------------------------
-- The row waits behind newer 'New' rows (Stage 3 polls newest-first), then ends Processed or Error.

SELECT public.drain_error_backlog_95(1);

-- --------------------------------------------------------------------------------------------
-- Step 2: schedule, hourly at :15 from 08:00 to 23:00 UTC.
-- --------------------------------------------------------------------------------------------

SELECT cron.schedule(
    'drain_error_backlog_95',
    '15 8-23 * * *',
    $$SELECT public.drain_error_backlog_95(50)$$
);

-- Verify (return_message holds the command tag, not the counts; use the yield query below):
--   SELECT jobid, schedule, command, active FROM cron.job WHERE jobname = 'drain_error_backlog_95';
--   SELECT status, return_message, start_time FROM cron.job_run_details
--   WHERE jobid = (SELECT jobid FROM cron.job WHERE jobname = 'drain_error_backlog_95')
--   ORDER BY start_time DESC LIMIT 5;
--
-- Pause on a 429 burst or when the queues below keep growing (0 'New' on 2026-09-24):
--   SELECT status, count(*) FROM public.snippets WHERE status IN ('New', 'Ready for review') GROUP BY 1;
--   SELECT cron.unschedule('drain_error_backlog_95');

-- --------------------------------------------------------------------------------------------
-- Yield per day: at_95 = back in the feed, capped_40 = capped for lack of evidence.
-- --------------------------------------------------------------------------------------------

SELECT l.batch,
       count(*) AS requeued,
       count(*) FILTER (WHERE s.status = 'Processed') AS processed,
       count(*) FILTER (WHERE s.status = 'Error') AS error,
       count(*) FILTER (WHERE s.status NOT IN ('Processed', 'Error')) AS in_flight,
       count(*) FILTER (WHERE s.status = 'Processed' AND (s.confidence_scores->>'overall')::integer >= 95) AS at_95,
       count(*) FILTER (WHERE s.status = 'Processed' AND (s.confidence_scores->>'overall')::integer = 40) AS capped_40,
       count(*) FILTER (WHERE s.status = 'Processed' AND (s.confidence_scores->>'overall')::integer < 40) AS under_40,
       count(*) FILTER (WHERE s.status = 'Processed'
                          AND s.confidence_scores->>'verification_status' = 'verified_true') AS verified_true
FROM public.snippet_requeue_log l
JOIN public.snippets s ON s.id = l.snippet
WHERE l.batch LIKE 'drain-95-%'
GROUP BY 1 ORDER BY 1;

-- --------------------------------------------------------------------------------------------
-- Rollback. Unschedule this job (and sweep_retryable_errors, if scheduled) first. Only rows no worker
-- has touched since the drain (updated_at still equals the log's requeued_at, same transaction);
-- rolled-back rows keep their log entry, so the drain skips them afterwards.
-- --------------------------------------------------------------------------------------------
--   BEGIN;
--   UPDATE public.snippets s
--   SET status            = l.previous_status,
--       error_message     = l.previous_error,
--       analysis_attempts = greatest(s.analysis_attempts - 1, 0)
--   FROM public.snippet_requeue_log l
--   WHERE s.id = l.snippet
--     AND l.batch LIKE 'drain-95-%'
--     AND s.status = 'New'
--     AND s.updated_at <= l.requeued_at;
--   COMMIT;
