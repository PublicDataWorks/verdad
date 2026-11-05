-- VER-454 item 2: index for the reserve RPC's ORDER BY priority DESC, recorded_at DESC over New snippets.
-- Build after 20261104100000.
--
-- *** Run OUTSIDE a transaction: CONCURRENTLY cannot run in a transaction block or through the Management API
-- *** (use a one-shot pg_cron job). A plain CREATE INDEX would lock snippets (7.5 GB) for the whole heap scan.
-- Verify: SELECT indisvalid FROM pg_index WHERE indexrelid = 'public.idx_snippets_new_priority'::regclass;
-- An interrupted build leaves an INVALID index: drop it with the rollback line and build again.
-- Rollback: DROP INDEX CONCURRENTLY IF EXISTS public.idx_snippets_new_priority;

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_snippets_new_priority
    ON public.snippets (priority DESC, recorded_at DESC)
    WHERE status = 'New';
