-- cleanup_2026_09 / step 05: roll back ONE BATCH of quarantined snippets (WRITES).
--
-- Restores snippets.status to snippet_quarantine_log.previous_status (normally
-- 'Processed', which puts them straight back into the feed) for every log row
-- of the chosen batch that has not been restored yet, and stamps restored_at.
--
-- Only rows whose snippet is still 'Quarantined' are touched. A snippet that was
-- already re-queued by 09 (status 'New', restored_at stamped there) or that has
-- since been reprocessed is left alone.
--
-- Runs in chunks of up to 5,000 so it stays under statement_timeout; repeat
-- until the UPDATE reports 0 rows. To undo the whole cleanup run it once per
-- batch name.

BEGIN;

WITH params AS (
    SELECT 'cleanup-2026-09-narrow'::text AS batch,   -- <- edit: -narrow or -broad
           5000                          AS chunk_size
),
todo AS (
    SELECT l.id AS log_id, l.snippet, l.previous_status
    FROM public.snippet_quarantine_log l
    JOIN public.snippets s ON s.id = l.snippet
    CROSS JOIN params p
    WHERE l.batch = p.batch
      AND l.restored_at IS NULL
      AND s.status = 'Quarantined'
    ORDER BY l.quarantined_at
    LIMIT (SELECT chunk_size FROM params)
),
restored AS (
    UPDATE public.snippets s
    SET    status = t.previous_status
    FROM   todo t
    WHERE  s.id = t.snippet
      AND  s.status = 'Quarantined'
    RETURNING s.id
)
UPDATE public.snippet_quarantine_log l
SET    restored_at = now()
FROM   restored r
WHERE  l.snippet = r.id
  AND  l.batch = (SELECT batch FROM params)
  AND  l.restored_at IS NULL;

COMMIT;

-- Verify (read-only):
-- SELECT batch, count(*) FILTER (WHERE restored_at IS NULL) AS still_quarantined,
--        count(*) FILTER (WHERE restored_at IS NOT NULL) AS restored
-- FROM public.snippet_quarantine_log GROUP BY batch;
-- SELECT count(*) FROM public.snippets WHERE status = 'Quarantined';
