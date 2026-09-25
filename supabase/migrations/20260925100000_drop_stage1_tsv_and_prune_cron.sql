-- VER-410: shrink the database back under the Small compute's 50 GB recommendation.
--
-- stage_1_llm_responses.tsv_transcription (8.4 GB) and its GIN index (1.9 GB, 30 scans ever) back only
-- get_recordings_preview, which main of verdad-frontend never calls (only the unmerged `browser` branch), and
-- the finished tsv backfill (cron job every minute, backfill_control paused). The trigger writes the column on
-- every insert, so it goes in the same transaction. The column's TOAST space returns on the next table rewrite.
--
-- pg_cron never prunes cron.job_run_details (1.18M rows by 25 Sep 2026, see 20260918040000); keep 7 days.
--
-- Rollback: recreate the column, trigger, functions, backfill_control and index from
-- 20260915000000_baseline_public_schema.sql, then backfill tsv_transcription with to_tsvector('spanish', ...).

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_cron') THEN
        PERFORM cron.unschedule('tsv_backfill_job') WHERE EXISTS (SELECT 1 FROM cron.job WHERE jobname = 'tsv_backfill_job');
    END IF;
END $$;

DROP TRIGGER IF EXISTS trg_update_tsv_transcription ON public.stage_1_llm_responses;
DROP FUNCTION IF EXISTS public.update_tsv_transcription();
DROP FUNCTION IF EXISTS public.run_tsv_backfill();
DROP FUNCTION IF EXISTS public.get_recordings_preview(timestamp with time zone, integer, jsonb, text);
DROP TABLE IF EXISTS public.backfill_control;
DROP INDEX IF EXISTS public.idx_stage1_tsv_transcription;
ALTER TABLE public.stage_1_llm_responses DROP COLUMN IF EXISTS tsv_transcription;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_cron') THEN
        PERFORM cron.schedule('prune_cron_job_run_details', '20 3 * * *',
            $cmd$DELETE FROM cron.job_run_details WHERE end_time < now() - interval '7 days'$cmd$);
    END IF;
END $$;
