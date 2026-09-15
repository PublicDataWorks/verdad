-- cleanup_2026_09 / step 09: re-queue ONE CHUNK of quarantined snippets for reprocessing (WRITES).
--
-- ONLY after the fixed pipeline code and prompts (evidence gate + temporal
-- context hotfix) are deployed. Setting status = 'New' hands the snippet to the
-- Stage 3 poller (fetch_a_new_snippet_and_reserve_it selects status = 'New'
-- ORDER BY recorded_at DESC), which re-analyses it and, if it passes, moves it
-- on to 'Ready for review' / 'Processed'. Snippets that fail the new gates
-- never come back above the feed threshold.
--
-- 500 newest-first per run so re-queued work does not starve live recordings
-- (the poller also takes newest first). Repeat until the UPDATE reports 0 rows.
-- The Python equivalent, src/scripts/reprocess_snippets.py, is being added on
-- the hotfix branch; use one or the other, not both at once.
--
-- GUARD: do not run for a batch until 04b_snapshot_analyses.sql has a snapshot
-- for every log row of that batch (snapshot count = log count; query at the end
-- of 04b and in README.md). Reprocessing overwrites the analysis columns.
--
-- The matching snippet_quarantine_log rows get restored_at stamped so they no
-- longer count as "currently quarantined" and 05 will not try to restore them.

BEGIN;

WITH params AS (
    SELECT 'cleanup-2026-09-narrow'::text AS batch,   -- <- edit: -narrow or -broad
           500                           AS chunk_size
),
picked AS (
    SELECT s.id
    FROM public.snippets s
    JOIN public.snippet_quarantine_log l ON l.snippet = s.id
    CROSS JOIN params p
    WHERE s.status = 'Quarantined'
      AND l.batch = p.batch
      AND l.restored_at IS NULL
    ORDER BY s.recorded_at DESC
    LIMIT (SELECT chunk_size FROM params)
    FOR UPDATE OF s SKIP LOCKED
),
requeued AS (
    UPDATE public.snippets s
    SET    status = 'New'
    FROM   picked
    WHERE  s.id = picked.id
      AND  s.status = 'Quarantined'
    RETURNING s.id
)
UPDATE public.snippet_quarantine_log l
SET    restored_at = now()
FROM   requeued r
WHERE  l.snippet = r.id
  AND  l.batch = (SELECT batch FROM params)
  AND  l.restored_at IS NULL;

COMMIT;

-- Watch progress (read-only):
-- SELECT status, count(*) FROM public.snippets
-- WHERE id IN (SELECT snippet FROM public.snippet_quarantine_log) GROUP BY status;
