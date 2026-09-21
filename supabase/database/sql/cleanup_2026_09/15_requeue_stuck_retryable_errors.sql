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
-- analysis_attempts = 0 on all but 4 of ~276,000 Error rows as of 2026-09-21 (the 4 are the
-- '[manual] held' rows noted under step 2).
--
-- Measured on production 2026-09-21 (read-only):
--   sweeper-eligible Error rows since June       : 101,755 (92,877 route to New, 8,878 to Ready for review)
--   of those, scoring 95+ and recorded since 2026-08-01 : ~2,800
--   of those, tagged Election Integrity          : 101 (step 2)
--   Stage 3 throughput : 2,800-3,700/day; New queue ~3,700 rows recorded 2-5 Sep, live rows
--                        clear within hours; ~40% slower 00:00-07:00 UTC (Gemini daily Pro cap)
--   Stage 4 throughput : 46-178/day over 14-20 Sep; cannot complete reviews 00:00-07:00 UTC
--
-- Routing. The sweeper sends a '[Stage 4]' failure back to 'Ready for review', where Stage 4
-- re-judges it on the Stage 3 evidence already in grounding_metadata. For the step-2 rows that
-- evidence predates the tool record (PR #98): 67 of 101 hold no contradicts_claim result (the
-- gate caps them to 40) and the other 34 hold contradicting URLs with url_observed_in_tools
-- unset, mostly politifact / factcheck / snopes / apnews links of the kind the VER-391 audit
-- found 85-90% dead, so Stage 4 would restore 95 on citations nobody can verify. Step 2 sends
-- every row to 'New' instead: a full Stage 3 re-run under today's pipeline (search fixed
-- 2026-09-21, VER-390; only tool-returned article URLs count since PR #98) is the only route
-- where a 95 means something. ~100k Pro tokens per row, ~2% of the daily quota for 105 rows.
--
-- Rajiv's sessions asked on 19 Sep (VER-389 comments) to hold this set until the pipeline
-- cannot call a true post-cutoff event 'false' on model knowledge alone (VER-391 item 4, not
-- built). That was argued against the pre-VER-390/391 pipeline; under today's gates a re-run
-- reaches 95 only on a tool-returned article, the bar live rows meet. Step 2 needs Rajiv's go.
--
-- ============================================================================================
-- How to run
-- ============================================================================================
-- Paste each step separately in the Supabase SQL editor and check its verification query
-- before moving on. Steps 0 and 2 are ordinary DDL/DML in explicit transactions. Step 3
-- schedules a cron job and can be undone with cron.unschedule.
--
-- Step 2 records every row it touches in public.snippet_requeue_log (step 0). That log is what
-- makes verification and rollback exact: once step 3 is running, the sweeper also sets
-- analysis_attempts = 1 on rows of its own, so any predicate keyed on analysis_attempts alone
-- would sweep up unrelated work. Always scope to the log.

-- --------------------------------------------------------------------------------------------
-- Step 0: audit log, so step 2 is reversible and verifiable by exact row set.
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
-- Step 1: DONE, do not run. Carlos's snippet 3e53d8e1-fdbd-4c4c-a692-f34be0b10962.
-- --------------------------------------------------------------------------------------------
-- Re-queued on 2026-09-19 by an earlier revision, capped to 40 by the gate, then restored to
-- Processed 95 by hand with a regrounded explanation (batch unmask-2026-09-19-carlos, PR #120,
-- PR #121), as were fb43bf56 and c253e70f from the same broadcast. Re-queueing any of the three
-- would overwrite that text (submit_snippet_review replaces explanation and confidence_scores).

-- --------------------------------------------------------------------------------------------
-- Step 2: the 101 election-tagged snippets scoring 95+ stranded since 2026-08-01.
-- --------------------------------------------------------------------------------------------
-- The pick predicate mirrors sweep_retryable_errors() exactly, including the
-- analysis_attempts < 3 ceiling and the excluded 'skipped_backlog' / 'Intentionally Hidden'
-- markers, so this file and the sweeper can never fight over the same row.
--
-- Every row goes to 'New' (see the header), '[Stage 4]' failures included. The second branch
-- picks up four Fulton rows (95+, Jul-Aug) parked by hand on 19 Sep under a '[manual] held'
-- marker the sweeper never matches. Dry run 2026-09-21: 101 + 4 rows.

BEGIN;

WITH picked AS (
    SELECT id, status, error_message
    FROM public.snippets
    WHERE status = 'Error'
      AND analysis_attempts < 3
      AND (
            (
                  recorded_at >= '2026-08-01'
              AND (confidence_scores->>'overall')::integer >= 95
              AND confidence_scores::text ILIKE '%Election Integrity%'
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
            )
         OR (
                  error_message LIKE '[manual] held VER-389 re-queue%'
              AND id IN ('a09b0842-f661-4dc5-997e-94a0861b115c',
                         'b8f8e3ea-7765-45d4-b59b-e457f7b20ed1',
                         '961d43c5-6c5b-413d-8a2b-947c24affd1e',
                         '2dc8cf14-8db5-46ed-a051-507ba502b4e7')
            )
      )
    ORDER BY recorded_at DESC
    LIMIT 200
    FOR UPDATE SKIP LOCKED
),
moved AS (
    UPDATE public.snippets s
    SET status            = 'New'::public.processing_status,
        error_message     = NULL,
        analysis_attempts = s.analysis_attempts + 1
    FROM picked p
    WHERE s.id = p.id
    RETURNING s.id, p.status AS previous_status, p.error_message AS previous_error, s.status AS new_status
)
INSERT INTO public.snippet_requeue_log (snippet, previous_status, previous_error, new_status, batch)
SELECT id, previous_status, previous_error, new_status, 'requeue-2026-09-21-ver389-step2'
FROM moved
ON CONFLICT (snippet, batch) DO UPDATE
    SET previous_status = EXCLUDED.previous_status,
        previous_error  = EXCLUDED.previous_error,
        new_status      = EXCLUDED.new_status,
        requeued_at     = now();

COMMIT;

-- Verify against the log, not against analysis_attempts: once step 3 is running the sweeper
-- also produces rows with analysis_attempts = 1, and they are not ours.
-- Expect 105 rows, all New (2026-09-21 dry run: 101 + the 4 held).
--   SELECT l.new_status, count(*)
--   FROM public.snippet_requeue_log l
--   WHERE l.batch = 'requeue-2026-09-21-ver389-step2'
--   GROUP BY 1;
--
-- Nothing eligible left behind (same pick predicate; a non-zero result means rows that still
-- qualify, not rows the guards excluded on purpose; the LIMIT 200 above only exists so a grown
-- set cannot be moved in one go by accident):
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
-- Progress and yield (how many came back Processed at 95+ vs capped vs errored again):
--   SELECT s.status,
--          count(*) FILTER (WHERE (s.confidence_scores->>'overall')::integer >= 95) AS at_95,
--          count(*) AS rows
--   FROM public.snippet_requeue_log l
--   JOIN public.snippets s ON s.id = l.snippet
--   WHERE l.batch = 'requeue-2026-09-21-ver389-step2'
--   GROUP BY 1 ORDER BY 1;

-- --------------------------------------------------------------------------------------------
-- Step 3: schedule the sweeper for the long tail.
-- --------------------------------------------------------------------------------------------
-- 91% of the 101,755 eligible rows route to New, so Stage 3 (2,800-3,700/day) is the constraint.
-- 50 rows an hour for the 16 hours outside the Gemini quota dead window (00:00-07:00 UTC) is
-- 800/day, ~25% on top of live work; Stage 3 polls newest-first, so re-queued (older) rows wait
-- behind live recordings. Raise p_batch only after a day of watching Stage 3 throughput; at
-- 800/day the tail takes ~4 months, which is the point: a drain, not a flood.
--
-- The sweeper still routes '[Stage 4]' failures (~8,900 in the tail) to Ready for review, where
-- Stage 4 re-judges pre-tool-record evidence (see the header). Changing that is a migration, not
-- this runbook: decide it before scheduling, or schedule and accept it.
--
-- Note the sweeper does NOT write to snippet_requeue_log. That is deliberate: the log exists to
-- delimit what this runbook did by hand, so that the rollback below can never touch the
-- sweeper's rows.

SELECT cron.schedule(
    'sweep_retryable_errors',
    '15 8-23 * * *',
    $$SELECT public.sweep_retryable_errors(50)$$
);

-- Verify the job exists and is active:
--   SELECT jobid, jobname, schedule, command, active FROM cron.job
--   WHERE jobname = 'sweep_retryable_errors';
-- After the first firing, check what it did:
--   SELECT jobid, status, return_message, start_time
--   FROM cron.job_run_details WHERE jobid =
--     (SELECT jobid FROM cron.job WHERE jobname = 'sweep_retryable_errors')
--   ORDER BY start_time DESC LIMIT 5;
-- Watch the backlog fall:
--   SELECT count(*) FROM public.snippets WHERE status = 'Error' AND analysis_attempts < 3;
--
-- Unschedule:  SELECT cron.unschedule('sweep_retryable_errors');

-- ============================================================================================
-- Rolling step 2 back (only if a re-queue turns out to be wrong)
-- ============================================================================================
-- Scoped to the rows this runbook moved, via the log, and restores what the log recorded: the
-- previous status and error message, and the attempt the row never used. With the original
-- error message back the row is sweeper-eligible again; unschedule step 3 first if that is not
-- wanted. Do not substitute a predicate on analysis_attempts: after step 3 the sweeper produces
-- rows that look identical by that measure.
--
--   BEGIN;
--   UPDATE public.snippets s
--   SET status            = l.previous_status,
--       error_message     = l.previous_error,
--       analysis_attempts = greatest(s.analysis_attempts - 1, 0)
--   FROM public.snippet_requeue_log l
--   WHERE s.id = l.snippet
--     AND l.batch = 'requeue-2026-09-21-ver389-step2'
--     AND s.status = 'New';
--   COMMIT;
--
-- Only meaningful before Stage 3 picks a row up, which is what the status condition enforces.
