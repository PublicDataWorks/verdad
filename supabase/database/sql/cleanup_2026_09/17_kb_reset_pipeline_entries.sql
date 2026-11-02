-- Knowledge base reset: deactivate every active pipeline-written entry in one logged batch (VER-413, VER-403 step 2).
-- EXECUTED 2026-09-28 02:28 UTC: 7,583 rows in kb_deactivation_log, active kb_entries 7,601 -> 18.
--
-- Pipeline-written = created_by_model starts with 'gemini' (stage_1/kb_context.is_pipeline_authored). The 18 kept
-- are analyst-written (analyst-seed-2026-09-17 x7, claude-opus-4-6-downvote-review x11). Stage 4 stopped writing
-- on 2026-09-25 (VER-412). Same mechanism as 07/08: embeddings go to 'Deactivated', not deleted.
-- Paste each step separately in the Supabase SQL editor.

-- --------------------------------------------------------------------------------------------
-- Step 0: dry run (read-only). 7,583 on 2026-09-28.
-- --------------------------------------------------------------------------------------------

SELECT created_by_model, count(*)
FROM public.kb_entries
WHERE status = 'active'
GROUP BY 1
ORDER BY 2 DESC;

-- --------------------------------------------------------------------------------------------
-- Step 1: deactivate (WRITES). Re-running is a no-op.
-- --------------------------------------------------------------------------------------------

BEGIN;

WITH picked AS (
    SELECT e.id, e.status AS previous_status
    FROM public.kb_entries e
    WHERE e.status = 'active'
      AND lower(coalesce(e.created_by_model, '')) LIKE 'gemini%'
      AND NOT EXISTS (SELECT 1 FROM public.kb_deactivation_log l
                      WHERE l.kb_entry = e.id AND l.batch = 'ver-403-reset-2026-09')
),
logged AS (
    INSERT INTO public.kb_deactivation_log (kb_entry, previous_status, reason, batch)
    SELECT id, previous_status, 'pipeline_written_reset', 'ver-403-reset-2026-09' FROM picked
    ON CONFLICT (kb_entry, batch) DO NOTHING
    RETURNING kb_entry
),
deactivated AS (
    UPDATE public.kb_entries e
    SET    status              = 'deactivated',
           deactivation_reason = 'ver-403-reset: pipeline_written_reset',
           updated_at          = now()
    FROM   logged
    WHERE  e.id = logged.kb_entry
      AND  e.status = 'active'
    RETURNING e.id
)
UPDATE public.kb_entry_embeddings kee
SET    status     = 'Deactivated',
       updated_at = now()
FROM   deactivated d
WHERE  kee.kb_entry = d.id
  AND  kee.status = 'Processed';

COMMIT;

-- Verify: active 18, batch 7,583, 'Processed' embeddings 18.
--   SELECT status, count(*) FROM public.kb_entries GROUP BY 1;
--   SELECT count(*) FROM public.kb_deactivation_log WHERE batch = 'ver-403-reset-2026-09';
--   SELECT status, count(*) FROM public.kb_entry_embeddings GROUP BY 1;

-- --------------------------------------------------------------------------------------------
-- Rollback (WRITES). Restores the batch; to re-admit a subset, add "AND l.kb_entry IN (...)" to todo.
-- Entries deactivated or superseded since for another reason are left alone.
-- --------------------------------------------------------------------------------------------

BEGIN;

WITH todo AS (
    SELECT l.kb_entry, l.previous_status
    FROM public.kb_deactivation_log l
    JOIN public.kb_entries e ON e.id = l.kb_entry
    WHERE l.batch = 'ver-403-reset-2026-09'
      AND l.restored_at IS NULL
      AND e.status = 'deactivated'
      AND e.deactivation_reason LIKE 'ver-403-reset:%'
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
  AND  l.batch = 'ver-403-reset-2026-09'
  AND  l.restored_at IS NULL;

COMMIT;
