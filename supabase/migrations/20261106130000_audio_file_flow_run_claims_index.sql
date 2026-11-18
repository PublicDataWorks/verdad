-- VER-463: index for release_flow_run_audio_files. Its UPDATEs filter on claimed_by_flow_run + status = 'Processing';
-- without this they seq-scan audio_files and the Stage 1 cancel hook hits the 8 s statement timeout.
-- Build after 20261106100000.
--
-- *** Run OUTSIDE a transaction: CONCURRENTLY cannot run in a transaction block or through the Management API
-- *** (use a one-shot pg_cron job).
-- Verify: SELECT indisvalid FROM pg_index
--     WHERE indexrelid = 'public.idx_audio_files_processing_claimed_by_flow_run'::regclass;
-- An interrupted build leaves an INVALID index: drop it with the rollback line and build again.
-- Rollback: DROP INDEX CONCURRENTLY IF EXISTS public.idx_audio_files_processing_claimed_by_flow_run;

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_audio_files_processing_claimed_by_flow_run
    ON public.audio_files (claimed_by_flow_run)
    WHERE status = 'Processing';
