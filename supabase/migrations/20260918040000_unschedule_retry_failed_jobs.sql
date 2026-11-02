-- Unschedule the broken pg_cron job `retry_failed_jobs` (VER-355).
--
-- The job was created on 2024-09-06 (`*/10 * * * *`, `SELECT retry_failed_jobs();`) and the function it calls
-- has not existed in the database at any point covered by the baseline dump (see the note at the bottom of
-- 20260915000000_baseline_public_schema.sql). Every run failed with "function retry_failed_jobs() does not
-- exist": 144 failed rows a day in cron.job_run_details, and nothing in the repo or the frontend references
-- the job or the function. The retry role it was presumably meant to play is now covered by
-- sweep_stuck_snippets (VER-371) and sweep_retryable_errors (VER-382).
--
-- Applied to production 2026-09-18 02:20 UTC via the Supabase connector; cron.job afterwards holds exactly
-- sweep_stuck_snippets and tsv_backfill_job. Guarded so it is a no-op wherever the job is already gone.
--
-- Not done here: cron.job_run_details holds ~1.17M rows (mostly tsv_backfill_job every minute plus this job's
-- failures) and pg_cron never prunes it; a periodic
--   DELETE FROM cron.job_run_details WHERE end_time < now() - interval '7 days'
-- is worth its own decision.

SELECT cron.unschedule('retry_failed_jobs')
WHERE EXISTS (SELECT 1 FROM cron.job WHERE jobname = 'retry_failed_jobs');
