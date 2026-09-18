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
--           WHERE location_state IS NULL AND radio_station_code IS NULL;
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
--   SELECT count(*) FILTER (WHERE location_state IS NULL AND audio_file IS NOT NULL) AS remaining,
--          count(*)
--   FROM public.snippets;
--
-- `remaining` does NOT go to 0 if any audio_files row has BOTH location_state and
-- radio_station_code NULL -- see the note on the inner SELECT below. Count those first so the
-- expected floor is known before the backfill starts:
--   SELECT count(*) FROM public.snippets s JOIN public.audio_files a ON a.id = s.audio_file
--   WHERE a.location_state IS NULL AND a.radio_station_code IS NULL;
-- Treat that number (and not 0) as "done" for those rows; they are snippets whose audio file has
-- no station metadata at all, and they were invisible to a states/sources filter before this
-- change too (the old CTEs matched on the same NULL columns).
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
          -- Only rows that still have nothing AND whose audio file has something to copy. The
          -- second condition is what makes the loop terminate: a snippet whose audio_files row
          -- has both columns NULL would be "updated" to NULL every batch and selected again
          -- forever. Those rows stay NULL; see the Verification block for the expected leftover.
          SELECT s2.id
          FROM public.snippets s2
          JOIN public.audio_files a2 ON a2.id = s2.audio_file
          WHERE s2.audio_file IS NOT NULL
            AND s2.location_state IS NULL
            AND s2.radio_station_code IS NULL
            AND (a2.location_state IS NOT NULL OR a2.radio_station_code IS NOT NULL)
          ORDER BY s2.id
          LIMIT p_batch
          FOR UPDATE OF s2 SKIP LOCKED
      );

    GET DIAGNOSTICS updated = ROW_COUNT;
    RETURN updated;
END;
$function$;

COMMENT ON FUNCTION public.backfill_snippets_location(integer) IS
    'One batch of the VER-387 backfill of snippets.location_state / radio_station_code from audio_files. Returns rows updated; call repeatedly until it returns 0.';
