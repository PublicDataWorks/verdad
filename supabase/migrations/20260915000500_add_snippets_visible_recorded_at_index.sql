-- Partial index that serves the default ("latest") page of get_snippets directly.
--
-- get_snippets (20260915000400_get_snippets_include_count.sql) orders the default feed with
-- "ORDER BY recorded_at DESC, id DESC LIMIT page_size OFFSET ..." over the visible snippets
-- (status = 'Processed' AND (confidence_scores->>'overall')::int >= 95). The existing
-- idx_snippets_processed_recorded_at (recorded_at DESC) WHERE status = 'Processed' lacks the
-- confidence predicate: measured on production 2026-09-15, 954 of the first 1,138 index
-- entries the planner walked failed the confidence filter (575 ms cold for page 0 without a
-- count), and the count-included first page still fell back to a 33k-block bitmap heap scan
-- of every visible row (4.3 s cold). With this index the same ORDER BY is an Index Only Scan
-- over exactly the visible rows (hypopg estimate: total cost 17.75 for the first page vs
-- ~30,000 for the bitmap scan), and (id DESC) as the second key matches the deterministic
-- tiebreak used by the function so no extra sort is needed.
--
-- Only ~43k of the 505k snippets satisfy the predicate, so the index is small (a few MB).
--
-- *** MUST be run OUTSIDE a transaction (e.g. as its own statement in the Supabase SQL editor,
-- *** not via a migration runner that wraps files in BEGIN/COMMIT): CREATE INDEX CONCURRENTLY
-- *** cannot run inside a transaction block. CONCURRENTLY avoids blocking writes to snippets
-- *** (the processing pipeline) during the build.
-- If the build is interrupted it leaves an INVALID index; check with
--   SELECT indexrelid::regclass FROM pg_index WHERE NOT indisvalid;
-- and DROP INDEX CONCURRENTLY it before re-running.
-- Verify afterwards:
--   SELECT indisvalid FROM pg_index WHERE indexrelid = 'idx_snippets_visible_recorded_at'::regclass;
-- Rollback: DROP INDEX CONCURRENTLY IF EXISTS public.idx_snippets_visible_recorded_at; (also outside a transaction)

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_snippets_visible_recorded_at
    ON public.snippets (recorded_at DESC, id DESC)
    WHERE status = 'Processed' AND (confidence_scores->>'overall')::int >= 95;
