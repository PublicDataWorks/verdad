-- Re-adds an index on audio_files.radio_station_code, which has had no index since
-- idx_audio_files_radio_station was dropped in 20260129_cleanup_unused_indexes.sql
-- (renamed to 20260129202429_cleanup_unused_indexes.sql by PR #83).
-- Station ("sources") filters in get_snippets / get_trending_topics currently seq-scan or
-- pkey-probe the 1.55M-row, 573 MB audio_files heap (2-4 s warm, 8 s+ cold).
--
-- Why (radio_station_code, id) and not just (radio_station_code): tested 2026-09-14 inside a
-- rolled-back transaction on production. With a single-column index the planner still probes
-- audio_files by primary key for every visible snippet and reads heap pages; with the
-- composite index the probe is an Index Only Scan ("radio_station_code = ANY(...) AND id =
-- s.audio_file", 0 heap fetches, ~0.014 ms/probe), and the "station -> audio_file ids" lookup
-- used by get_snippets is index-only too. Built size: 72 MB.
--
-- The functions only benefit once their filter is written as "radio_station_code = ANY(text[])"
-- (see 20260915000300_optimize_get_trending_topics.sql and 20260915000400_get_snippets_include_count.sql);
-- the current "IN (SELECT jsonb_array_elements_text(...))" form is estimated as matching
-- every row and never uses an index.
--
-- *** MUST be run OUTSIDE a transaction (e.g. as its own statement in the Supabase SQL editor,
-- *** not via a migration runner that wraps files in BEGIN/COMMIT): CREATE INDEX CONCURRENTLY
-- *** cannot run inside a transaction block. CONCURRENTLY avoids blocking writes to
-- *** audio_files (the recording pipeline) during the ~10 s build.
-- If the build is interrupted it leaves an INVALID index; check with
--   SELECT indexrelid::regclass FROM pg_index WHERE NOT indisvalid;
-- and DROP INDEX CONCURRENTLY it before re-running.

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_audio_files_radio_station_code_id
    ON public.audio_files (radio_station_code, id);
