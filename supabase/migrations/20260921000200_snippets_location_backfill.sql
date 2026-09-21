-- Backfill snippets.location_state / snippets.radio_station_code from audio_files (VER-387).
--
-- Companion to 20260921000100 (columns + sync triggers). The triggers only cover new and updated
-- rows; the rows that already exist need one batched pass. Only the VISIBLE ones (status =
-- 'Processed' AND overall >= 95, ~43k of 563k) are backfilled: they are all get_snippets reads,
-- and the copy trigger fires on every status / confidence_scores write, so any other row is
-- filled by the write that makes it visible. get_snippets must NOT be switched to the
-- denormalized columns (20260921000400) until this reports 0 remaining, or filtered pages come
-- back empty for rows that are still NULL.
--
-- ============================================================================================
-- Why visible rows only (measured 2026-09-21 11:31 UTC on production)
-- ============================================================================================
-- snippets carries 35 indexes, 17 of them pgroonga over the full text of transcription,
-- translation, title, summary and explanation. Every backfill UPDATE is non-HOT (0 HOT of the
-- first 2,365 rows: the heap pages have no free space) and re-enters the row into all of them,
-- detoast + unaccent + tokenize: ~50 ms per row. A 5000-row batch hit the 2-minute
-- statement_timeout inside verdad_unaccent. The whole table would be ~8 hours of pgroonga churn
-- for 520k rows nobody can see; the visible set is ~36 minutes.
--
-- ============================================================================================
-- How to run it
-- ============================================================================================
-- Batches of 1000 (~50 s each, under the 2-minute statement_timeout with margin), ~43 of them.
-- (a) By hand, in the Supabase SQL editor, repeat until it returns 0:
--       SELECT public.backfill_snippets_location(1000);
--
-- (b) As a one-off pg_cron job (pg_cron 1.6 is installed), every minute:
--       SELECT cron.schedule('backfill-snippets-location', '* * * * *',
--                            $$SELECT public.backfill_snippets_location(1000)$$);
--     and when the verification query below reports 0 remaining:
--       SELECT cron.unschedule('backfill-snippets-location');
--     Check progress with:
--       SELECT jobid, status, return_message, start_time
--       FROM cron.job_run_details ORDER BY start_time DESC LIMIT 10;
--
-- Each call is its own transaction (one UPDATE), so it can be stopped at any point and resumed;
-- FOR UPDATE SKIP LOCKED means it never blocks the pipeline's own writes.
--
-- Before the first batch, build a throwaway partial index over the rows still to do, so each
-- batch is an index walk over exactly the remaining rows instead of a filter over the visible
-- set. It shrinks as the backfill progresses. Keep it until 20260921000400 has been applied:
-- that file's guard runs the same predicate. Both statements MUST run outside a transaction
-- (CONCURRENTLY):
--       CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_snippets_location_backfill
--           ON public.snippets (id)
--           WHERE radio_station_code IS NULL
--             AND status = 'Processed'::processing_status
--             AND ((confidence_scores ->> 'overall'::text))::integer >= 95;
--     ... run the batches, 20260921000300, 20260921000400 ...
--       DROP INDEX CONCURRENTLY IF EXISTS public.idx_snippets_location_backfill;
--
-- Every updated row is a new heap tuple (~43k dead ones). The autovacuum thresholds for the large
-- tables were tuned in 20260918020100_autovacuum_thresholds_large_tables.sql; check afterwards
--   SELECT relname, n_live_tup, n_dead_tup, last_autovacuum, last_autoanalyze
--   FROM pg_stat_user_tables WHERE relname = 'snippets';
-- If n_dead_tup is still large hours later, run `VACUUM (ANALYZE) public.snippets;` by hand
-- (plain VACUUM, never VACUUM FULL -- that takes an ACCESS EXCLUSIVE lock). The new columns have
-- no statistics until an ANALYZE runs; the README makes `ANALYZE public.snippets;` an explicit
-- step before the function swap rather than waiting for autoanalyze.
--
-- ============================================================================================
-- Verification
-- ============================================================================================
--   SELECT count(*) FILTER (WHERE radio_station_code IS NULL) AS remaining, count(*) AS visible
--   FROM public.snippets
--   WHERE status = 'Processed' AND (confidence_scores ->> 'overall')::integer >= 95;
--
-- Done means `remaining` = 0. audio_files.radio_station_code is NOT NULL, so there is no
-- permanent floor on this count; a row locked by the pipeline is skipped and picked up by the
-- next batch. Rows outside the visible set stay NULL by design.
--
-- location_state is allowed to stay NULL where audio_files.location_state is NULL. On production
-- on 2026-09-18 that was 0 snippets:
--   SELECT count(*) FROM public.snippets s JOIN public.audio_files a ON a.id = s.audio_file
--   WHERE a.location_state IS NULL;
-- Those rows (if any) match no states filter, exactly as before this change.
--
-- Side effect to know about: every backfilled row gets updated_at = now() from the existing
-- snippets_handle_updated_at trigger. Harmless for Processed rows (nothing reads their
-- updated_at for scheduling; sweep_stuck_snippets only looks at Processing / Reviewing).
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
    -- LIMIT NULL means "no limit" in PostgreSQL, and a non-positive batch is a mistake either way;
    -- refuse both rather than silently rewriting the whole table in one transaction.
    IF p_batch IS NULL OR p_batch <= 0 THEN
        RAISE EXCEPTION 'backfill_snippets_location: p_batch must be a positive integer, got %', p_batch;
    END IF;

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
          -- Visible rows only (see the header); the predicate is the one idx_snippets_visible_cover
          -- and 20260921000300 use, character for character.
          SELECT s2.id
          FROM public.snippets s2
          WHERE s2.audio_file IS NOT NULL
            AND s2.radio_station_code IS NULL
            AND s2.status = 'Processed'::processing_status
            AND ((s2.confidence_scores ->> 'overall'::text))::integer >= 95
          ORDER BY s2.id
          LIMIT p_batch
          FOR UPDATE SKIP LOCKED
      );

    GET DIAGNOSTICS updated = ROW_COUNT;
    RETURN updated;
END;
$function$;

COMMENT ON FUNCTION public.backfill_snippets_location(integer) IS
    'One batch of the VER-387 backfill of snippets.location_state / radio_station_code from audio_files, visible rows only. Returns rows updated; call repeatedly until it returns 0.';
