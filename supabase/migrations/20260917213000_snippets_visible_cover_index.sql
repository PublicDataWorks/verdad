-- Covering index for the feed's page-0 count when a states / sources / languages filter is set.
--
-- Follow-up to 20260917210000_get_snippets_state_filter_plan.sql ("root cause B"). With a states or
-- sources filter the count in get_snippets has to read `audio_file` for every visible snippet, and
-- with a languages filter it has to read `language`. Neither column is in
-- idx_snippets_visible_recorded_at (20260915000500), so the planner does an Index Scan with one
-- random heap page per visible row (42,864 rows, ~42k buffers). Warm that is 0.2-0.4 s; cold, after
-- the feed has been idle, it is the 10-17 s that shows up as the 8 s statement_timeout Tamoa
-- reported ("adding Arizona/California breaks the filter", Feedback #8).
--
-- Measured on production 2026-09-17 (live get_snippets, page 0, p_include_count = true, as an
-- authenticated user), before this index:
--   states Florida + languages Spanish : 17.3 s cold   (standalone warm count: 244 ms, 41,845 buffers
--                                                       on the snippets leg, all heap)
--   states Arizona+California+Georgia  : 10.1 s cold, 3.9 s after the interim (audio_file-only) index
--   states Georgia                     : 10.7 s cold
-- With `audio_file` and `language` carried in the index as payload columns the states/sources/
-- languages count runs as an Index Only Scan over the 42.9k visible entries and never touches the
-- snippets heap. `language` averages 103 bytes per visible row, so the index is a few MB.
-- (`political_leaning` averages 1,340 bytes and is deliberately not included; the political-spectrum
-- filter is rare in PostHog and stays heap-bound.)
--
-- Supersedes the interim idx_snippets_visible_recorded_at_audio (built by hand 2026-09-17 21:07 UTC
-- from the note at the bottom of 20260917210000; removed below). idx_snippets_visible_recorded_at
-- (000500) is kept: it is 1.7 MB and still serves the unfiltered default page.
--
-- *** MUST be run OUTSIDE a transaction (paste each statement alone in the Supabase SQL editor, or
-- *** run through a one-off pg_cron job as was done on 2026-09-17): the CONCURRENTLY forms cannot
-- *** run inside a transaction block, and a plain CREATE INDEX would take a SHARE lock on snippets
-- *** for the length of a 505k-row heap scan, stalling the pipeline.
-- Verify: SELECT indisvalid FROM pg_index WHERE indexrelid = 'idx_snippets_visible_cover'::regclass;
-- Rollback: remove idx_snippets_visible_cover with the CONCURRENTLY form, outside a transaction.

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_snippets_visible_cover
    ON public.snippets (recorded_at DESC, id DESC)
    INCLUDE (audio_file, language)
    WHERE (status = 'Processed'::processing_status
           AND ((confidence_scores ->> 'overall'::text))::integer >= 95);

-- Interim index superseded by the one above (same key, fewer payload columns).
DROP INDEX CONCURRENTLY IF EXISTS public.idx_snippets_visible_recorded_at_audio;
