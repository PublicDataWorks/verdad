-- VER-466: the six live `>= 95` feed indexes again, with the per-model visible predicate of 20261109120100 (same
-- text, so feed counts stay Index Only Scans and the 2.5-era 90-94 rows stay out). Build before 20261109120100.
--
-- *** Run OUTSIDE a transaction, one statement at a time, with statement_timeout = 0 (CONCURRENTLY cannot run in a
-- *** transaction block or through the Management API).
-- Verify: SELECT indexrelid::regclass, indisvalid FROM pg_index WHERE indexrelid::regclass::text LIKE 'idx_snippets_feed%';
-- An interrupted build leaves an INVALID index: DROP INDEX CONCURRENTLY IF EXISTS it, then build again.
-- Rollback: DROP INDEX CONCURRENTLY IF EXISTS each idx_snippets_feed* index.

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_snippets_feed
    ON public.snippets (id)
    WHERE (status = 'Processed'::processing_status
           AND ((confidence_scores ->> 'overall'::text))::integer >= 90
           AND ((((confidence_scores ->> 'overall'::text))::integer >= 95)
                OR (analyzed_by LIKE 'gemini-3.%' AND reviewed_at IS NOT NULL)));

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_snippets_feed_recorded_at
    ON public.snippets (recorded_at DESC, id DESC)
    WHERE (status = 'Processed'::processing_status
           AND ((confidence_scores ->> 'overall'::text))::integer >= 90
           AND ((((confidence_scores ->> 'overall'::text))::integer >= 95)
                OR (analyzed_by LIKE 'gemini-3.%' AND reviewed_at IS NOT NULL)));

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_snippets_feed_cover
    ON public.snippets (recorded_at DESC, id DESC)
    INCLUDE (audio_file, language)
    WHERE (status = 'Processed'::processing_status
           AND ((confidence_scores ->> 'overall'::text))::integer >= 90
           AND ((((confidence_scores ->> 'overall'::text))::integer >= 95)
                OR (analyzed_by LIKE 'gemini-3.%' AND reviewed_at IS NOT NULL)));

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_snippets_feed_state
    ON public.snippets (location_state, recorded_at DESC, id DESC)
    INCLUDE (language)
    WHERE (status = 'Processed'::processing_status
           AND ((confidence_scores ->> 'overall'::text))::integer >= 90
           AND ((((confidence_scores ->> 'overall'::text))::integer >= 95)
                OR (analyzed_by LIKE 'gemini-3.%' AND reviewed_at IS NOT NULL)));

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_snippets_feed_station
    ON public.snippets (radio_station_code, recorded_at DESC, id DESC)
    INCLUDE (language)
    WHERE (status = 'Processed'::processing_status
           AND ((confidence_scores ->> 'overall'::text))::integer >= 90
           AND ((((confidence_scores ->> 'overall'::text))::integer >= 95)
                OR (analyzed_by LIKE 'gemini-3.%' AND reviewed_at IS NOT NULL)));

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_snippets_feed_political_leaning
    ON public.snippets ((((political_leaning ->> 'score'::text))::double precision))
    WHERE (status = 'Processed'::processing_status
           AND ((confidence_scores ->> 'overall'::text))::integer >= 90
           AND ((((confidence_scores ->> 'overall'::text))::integer >= 95)
                OR (analyzed_by LIKE 'gemini-3.%' AND reviewed_at IS NOT NULL)));
