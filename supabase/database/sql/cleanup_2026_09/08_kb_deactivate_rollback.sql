-- cleanup_2026_09 / step 08: roll back the knowledge-base deactivation (WRITES).
--
-- Restores kb_entries.status to kb_deactivation_log.previous_status ('active')
-- and clears the 'cleanup-2026-09: ...' deactivation_reason for every log row
-- of the batch that has not been restored yet, then stamps restored_at.
-- Only entries still 'deactivated' with our reason prefix are touched, so an
-- entry someone deactivated or superseded for another reason since is left alone.
-- Embeddings were never deleted (07 set kb_entry_embeddings.status = 'Deactivated');
-- this flips them back to 'Processed', so restored entries are searchable at once.

BEGIN;

WITH params AS (
    SELECT 'cleanup-2026-09-kb'::text AS batch
),
todo AS (
    SELECT l.kb_entry, l.previous_status
    FROM public.kb_deactivation_log l
    JOIN public.kb_entries e ON e.id = l.kb_entry
    CROSS JOIN params p
    WHERE l.batch = p.batch
      AND l.restored_at IS NULL
      AND e.status = 'deactivated'
      AND e.deactivation_reason LIKE 'cleanup-2026-09:%'
),
restored AS (
    UPDATE public.kb_entries e
    SET    status              = t.previous_status,
           deactivation_reason = NULL,
           updated_at          = now()
    FROM   todo t
    WHERE  e.id = t.kb_entry
    RETURNING e.id
),
embeddings_back AS (
    UPDATE public.kb_entry_embeddings kee
    SET    status     = 'Processed',
           updated_at = now()
    FROM   restored r
    WHERE  kee.kb_entry = r.id
      AND  kee.status = 'Deactivated'
    RETURNING kee.kb_entry
)
UPDATE public.kb_deactivation_log l
SET    restored_at = now()
FROM   restored r
WHERE  l.kb_entry = r.id
  AND  l.batch = (SELECT batch FROM params)
  AND  l.restored_at IS NULL;

COMMIT;

-- Verify (read-only):
-- SELECT status, count(*) FROM public.kb_entries GROUP BY status;
-- SELECT count(*) FILTER (WHERE restored_at IS NULL) AS still_deactivated,
--        count(*) FILTER (WHERE restored_at IS NOT NULL) AS restored
-- FROM public.kb_deactivation_log WHERE batch = 'cleanup-2026-09-kb';
-- SELECT status, count(*) FROM public.kb_entry_embeddings GROUP BY status;
