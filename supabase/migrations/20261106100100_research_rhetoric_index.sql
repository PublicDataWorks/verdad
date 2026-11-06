-- Partial index for the get_snippets research view's harmful-rhetoric arm (VER-462).
--
-- Second of two (20261106100000_research_view.sql, then this). In the research view a snippet is
-- visible when overall >= 95 OR it carries a research label OR
-- (confidence_scores->'harmful_rhetoric'->>'score')::int >= 70. The first arm is served by the
-- existing visible partial indexes and the second by snippets_pkey (s.id = ANY(uuid[])); this
-- index serves the third, so the planner can BitmapOr all three instead of filtering every
-- Processed row. Key shape mirrors idx_snippets_visible_recorded_at: (recorded_at DESC, id DESC).
-- The predicate must stay textually identical to the one in get_snippets (no COALESCE), or the
-- planner cannot prove the index applies.
--
-- The default feed never uses it: without p_filter.view = 'research' the arm is folded away.
-- Until Stage 3 prompt 1.8.0 writes harmful_rhetoric the index is empty; building it first is
-- cheapest (the scan still reads every Processed row, but inserts nothing).
--
-- *** MUST be run OUTSIDE a transaction (a one-off pg_cron job, as for 20260921000300 and
-- *** 20261104100100): the CONCURRENTLY form cannot run inside a transaction block or through the
-- *** Management API, and a plain CREATE INDEX would take a SHARE lock on snippets for the whole
-- *** heap scan, stalling the pipeline. The postgres role's 2-minute statement_timeout is too short
-- *** for a scan of snippets that detoasts confidence_scores; see
-- *** README_2026-11-06_research_view_apply_order.md.
-- Verify: SELECT indisvalid FROM pg_index WHERE indexrelid = 'public.idx_snippets_research_rhetoric'::regclass;
-- An interrupted build leaves an INVALID index behind: drop it with the rollback line and build again.
-- Rollback (also outside a transaction):
--   DROP INDEX CONCURRENTLY IF EXISTS public.idx_snippets_research_rhetoric;

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_snippets_research_rhetoric
    ON public.snippets (recorded_at DESC, id DESC)
    WHERE (status = 'Processed'::processing_status
           AND ((confidence_scores -> 'harmful_rhetoric'::text) ->> 'score'::text)::integer >= 70);
