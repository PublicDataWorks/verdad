-- Partial indexes that serve the states / sources filters from the denormalized columns (VER-387).
--
-- Third of four (20260921000100 columns+triggers, 20260921000200 backfill, this, then
-- 20260921000400 get_snippets). The new get_snippets filters on snippets.location_state /
-- snippets.radio_station_code directly instead of probing audio_files; these two indexes make
-- that an index-only walk over the visible subset (~43k of 505k rows) for both the page and the
-- page-0 count.
--
-- Key shape mirrors idx_snippets_visible_cover (20260917213000): the filter column first so it is
-- an equality index condition, then (recorded_at DESC, id DESC) so the default 'latest' ordering
-- and its LIMIT are satisfied by the index walk with no sort.
--
-- `language` is INCLUDEd as a payload column for the same reason it was added to
-- idx_snippets_visible_cover: the languages filter is evaluated in the same predicate
-- (s.language ->> 'primary_language'), it is the filter combination Tamoa actually uses
-- ("states Florida + languages Spanish"), and without it every candidate row costs one random
-- heap page. It averages ~103 bytes per visible row, so the payload is a few MB.
-- (political_leaning averages 1,340 bytes and is deliberately left out, as there.)
--
-- *** MUST be run OUTSIDE a transaction (paste each statement alone in the Supabase SQL editor, or
-- *** run through a one-off pg_cron job): the CONCURRENTLY form cannot run inside a transaction
-- *** block, and a plain CREATE INDEX would take a SHARE lock on snippets for the length of a
-- *** 505k-row heap scan, stalling the pipeline.
-- Verify (both must be true):
--   SELECT indisvalid FROM pg_index WHERE indexrelid = 'idx_snippets_visible_state'::regclass;
--   SELECT indisvalid FROM pg_index WHERE indexrelid = 'idx_snippets_visible_station'::regclass;
-- A CONCURRENTLY build that is interrupted leaves an INVALID index behind: drop it with the
-- CONCURRENTLY form and build again.
-- Rollback (also outside a transaction):
--   DROP INDEX CONCURRENTLY IF EXISTS public.idx_snippets_visible_state;
--   DROP INDEX CONCURRENTLY IF EXISTS public.idx_snippets_visible_station;
--
-- These can be built before the backfill finishes (they index NULLs too), but they are only
-- useful once it has.

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_snippets_visible_state
    ON public.snippets (location_state, recorded_at DESC, id DESC)
    INCLUDE (language)
    WHERE (status = 'Processed'::processing_status
           AND ((confidence_scores ->> 'overall'::text))::integer >= 95);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_snippets_visible_station
    ON public.snippets (radio_station_code, recorded_at DESC, id DESC)
    INCLUDE (language)
    WHERE (status = 'Processed'::processing_status
           AND ((confidence_scores ->> 'overall'::text))::integer >= 95);
