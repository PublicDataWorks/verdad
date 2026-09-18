-- Backfill snippets.location_state / snippets.radio_station_code from audio_files (VER-387).
--
-- Companion to 20260921000100 (columns + sync triggers). The triggers only cover new and updated
-- rows; the ~505k existing snippets need one batched pass. get_snippets must NOT be switched to
-- the denormalized columns (20260921000400) until this reports 0 remaining, or filtered pages
-- come back empty for rows that are still NULL.
--
-- ============================================================================================
-- How to run it
-- ============================================================================================
-- (a) By hand, in the Supabase SQL editor, repeat until it returns 0 (~100 batches at 5000):
--       SELECT public.backfill_snippets_location(5000);
--
-- (b) As a one-off pg_cron job (pg_cron 1.6 is installed), every minute:
--       SELECT cron.schedule('backfill-snippets-location', '* * * * *',
--                            $$SELECT public.backfill_snippets_location(5000)$$);
--     and when the verification query below reports 0 remaining:
--       SELECT cron.unschedule('backfill-snippets-location');
--     Check progress with:
--       SELECT jobid, status, return_message, start_time
--       FROM cron.job_run_details ORDER BY start_time DESC LIMIT 10;
--
-- Each call is its own transaction (one UPDATE), so it can be stopped at any point and resumed;
-- FOR UPDATE SKIP LOCKED means it never blocks the pipeline's own writes.
--
-- Before the first batch, build a throwaway partial index over the rows still to do. Without it
-- every batch walks snippets_pkey in id order and heap-checks the rows already filled (the skip
-- grows by 5000 per batch: ~25M visibility checks over the run); with it each batch is an
-- index walk over exactly the remaining rows. It shrinks as the backfill progresses and is
-- dropped at the end. Both statements MUST run outside a transaction (CONCURRENTLY):
--       CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_snippets_location_backfill
--           ON public.snippets (id)
--           WHERE radio_station_code IS NULL;
--     ... run the batches ...
--       DROP INDEX CONCURRENTLY IF EXISTS public.idx_snippets_location_backfill;
--
-- ============================================================================================
-- Bloat: run it off-peak
-- ============================================================================================
-- Every updated row is a new heap tuple, so this rewrites the whole 581 MB snippets heap into
-- dead tuples over the course of the backfill. The autovacuum thresholds for the large tables
-- were tuned in 20260918020100_autovacuum_thresholds_large_tables.sql, so autovacuum will pick
-- this up, but it needs time and I/O headroom: run off-peak and check afterwards
--   SELECT relname, n_live_tup, n_dead_tup, last_autovacuum
--   FROM pg_stat_user_tables WHERE relname = 'snippets';
-- If n_dead_tup is still large hours later, run `VACUUM (ANALYZE) public.snippets;` by hand
-- (plain VACUUM, never VACUUM FULL -- that takes an ACCESS EXCLUSIVE lock).
--
-- ============================================================================================
-- Verification
-- ============================================================================================
--   SELECT count(*) FILTER (WHERE radio_station_code IS NULL AND audio_file IS NOT NULL) AS remaining,
--          count(*) FILTER (WHERE status IN ('Processing', 'Reviewing'))              AS in_flight,
--          count(*)
--   FROM public.snippets;
--
-- Done means `remaining` = 0. The batches skip rows that are Processing / Reviewing (see the note
-- inside the function), so `remaining` plateaus at roughly `in_flight` (single digits on
-- production, 2026-09-18) while the pipeline is busy; keep calling the function (or leave the
-- cron job running) until a batch returns 0 with `remaining` = 0. audio_files.radio_station_code
-- is NOT NULL, so there is no permanent floor on this count.
--
-- location_state is allowed to stay NULL where audio_files.location_state is NULL. On production
-- on 2026-09-18 that was 0 snippets:
--   SELECT count(*) FROM public.snippets s JOIN public.audio_files a ON a.id = s.audio_file
--   WHERE a.location_state IS NULL;
-- Those rows (if any) match no states filter, exactly as before this change.
--
-- Side effect to know about: every backfilled row gets updated_at = now() from the existing
-- snippets_handle_updated_at trigger. That is harmless for Processed / Error / New rows (nothing
-- reads their updated_at for scheduling) and is why in-flight rows are excluded.
--
-- ============================================================================================
-- Transactionality and rollback
-- ============================================================================================
-- Creating the function is a plain transactional CREATE OR REPLACE. Running it is data movement,
-- not DDL. Rollback of the data: `UPDATE public.snippets SET location_state = NULL,
-- radio_station_code = NULL;` (or just drop the columns, see 20260921000100's rollback).
--
-- The function is KEPT after the backfill rather than dropped: it is inert once there is nothing
-- left to update (it returns 0 immediately), it costs nothing, and it is the tool to re-run if a
-- future bulk load ever bypasses the triggers (e.g. a restore into a table without them). It is
-- not SECURITY DEFINER, so only roles that can already UPDATE snippets can do anything with it.

CREATE OR REPLACE FUNCTION public.backfill_snippets_location(p_batch integer DEFAULT 5000)
RETURNS integer
LANGUAGE plpgsql
SET search_path = public, extensions, pg_temp
AS $function$
DECLARE
    updated integer;
BEGIN
    UPDATE public.snippets s
    SET location_state = a.location_state,
        radio_station_code = a.radio_station_code
    FROM public.audio_files a
    WHERE s.audio_file = a.id
      AND s.id IN (
          -- "Still to do" is radio_station_code IS NULL: audio_files.radio_station_code is NOT NULL
          -- (baseline schema), so every updated row leaves this set and the loop terminates.
          -- location_state is deliberately not part of the predicate: audio_files.location_state
          -- is nullable, and a snippet whose audio file has no state must be allowed to stay NULL
          -- without being re-selected forever.
          -- Rows in flight through the pipeline (Processing / Reviewing) are skipped: this UPDATE
          -- fires snippets_handle_updated_at, which bumps updated_at, and sweep_stuck_snippets
          -- (20260917080000) uses updated_at < now() - 2 h to requeue stuck rows, so touching an
          -- in-flight row here would hide it from the sweep for up to two hours. They are picked
          -- up by a later batch once their status changes.
          SELECT s2.id
          FROM public.snippets s2
          WHERE s2.audio_file IS NOT NULL
            AND s2.radio_station_code IS NULL
            AND s2.status NOT IN ('Processing', 'Reviewing')
          ORDER BY s2.id
          LIMIT p_batch
          FOR UPDATE SKIP LOCKED
      );

    GET DIAGNOSTICS updated = ROW_COUNT;
    RETURN updated;
END;
$function$;

COMMENT ON FUNCTION public.backfill_snippets_location(integer) IS
    'One batch of the VER-387 backfill of snippets.location_state / radio_station_code from audio_files. Returns rows updated; call repeatedly until it returns 0.';
