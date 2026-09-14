-- cleanup_2026_09 / step 07: deactivate the K1 UNION K2 UNION K3 knowledge-base entries (WRITES).
--
-- Do not run until Rajiv has approved the counts from 06 in Slack.
--
-- Section A creates the audit log (idempotent, same service-role-only RLS
-- pattern as snippet_quarantine_log). Section B does the deactivation in one
-- transaction: log first, then UPDATE exactly the logged rows. Re-running is a
-- no-op because entries already logged for the batch are skipped.
--
-- ~4,250 rows; the count query finishes in well under the 2-minute
-- statement_timeout, so no LIMIT loop is needed. If it ever times out, add
-- `LIMIT 2000` to the `picked` CTE and repeat.
--
-- Embeddings: search_kb_entries filters kb_entries.status = 'active', but
-- find_duplicate_kb_entries does not (it expects deactivated entries to have no
-- 'Processed' embedding). Both filter kb_entry_embeddings.status = 'Processed',
-- so the second UPDATE below marks the affected embeddings 'Deactivated' rather
-- than deleting them; 08 marks them 'Processed' again. Nothing else reads that
-- column (the pipeline only writes 'Processed' on insert). This deliberately
-- differs from SupabaseClient.deactivate_kb_entry, which deletes the row: a
-- deletion would force a re-embedding backfill on rollback.

-- ---------- Section A: audit log ----------
CREATE TABLE IF NOT EXISTS public.kb_deactivation_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    kb_entry        UUID NOT NULL REFERENCES public.kb_entries(id) ON DELETE CASCADE,
    previous_status public.kb_entry_status NOT NULL,
    reason          TEXT NOT NULL,
    batch           TEXT NOT NULL,
    deactivated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    restored_at     TIMESTAMPTZ NULL,
    UNIQUE (kb_entry, batch)
);

COMMENT ON TABLE public.kb_deactivation_log IS
    'cleanup_2026_09: which kb_entries were set to deactivated, why, in which batch, and whether they were restored.';

CREATE INDEX IF NOT EXISTS idx_kb_deactivation_log_kb_entry
    ON public.kb_deactivation_log (kb_entry);
CREATE INDEX IF NOT EXISTS idx_kb_deactivation_log_batch
    ON public.kb_deactivation_log (batch);

ALTER TABLE public.kb_deactivation_log ENABLE ROW LEVEL SECURITY;
-- No policies on purpose: service_role only.
GRANT ALL ON TABLE public.kb_deactivation_log TO service_role;

-- ---------- Section B: deactivate ----------
BEGIN;

WITH params AS (
    SELECT 'cleanup-2026-09-kb'::text AS batch
),
patterns AS (
    SELECT
        '(no|zero|absence of any) (credible |verifiable |public |official |online |such )?(evidence|records?|results?|reports?|information|mention|trace)|does not exist|do not exist|non-?existent|never (happened|occurred|existed|took place)|did not (happen|occur|take place)|yield(ed|s)? no|no search results' AS no_evidence,
        'fabricat|fictional|ficticio|never existed|does not exist|no existe' AS negative_fact
),
active AS (
    SELECT e.id, e.status, e.fact || ' ' || coalesce(e.related_claim, '') AS txt, e.created_by_snippet
    FROM public.kb_entries e
    CROSS JOIN params p
    WHERE e.status = 'active'
      -- idempotency: skip entries already logged for this batch
      AND NOT EXISTS (SELECT 1 FROM public.kb_deactivation_log l
                      WHERE l.kb_entry = e.id AND l.batch = p.batch)
),
k1 AS (
    SELECT a.id FROM active a CROSS JOIN patterns pt
    WHERE a.txt ~* pt.no_evidence OR a.txt ~* pt.negative_fact
),
k2 AS (
    SELECT a.id FROM active a
    WHERE NOT EXISTS (
        SELECT 1 FROM public.kb_entry_sources s
        WHERE s.kb_entry = a.id
          AND s.url ~* '^https?://'
          AND s.url NOT ILIKE '%example.com%'
          AND s.url NOT ILIKE '%web_research.com%'
          AND s.url NOT ILIKE '%google.com/search%')
),
k3 AS (
    SELECT a.id FROM active a
    WHERE a.created_by_snippet IS NOT NULL
      AND (EXISTS (SELECT 1 FROM public.user_like_snippets l
                   WHERE l.snippet = a.created_by_snippet AND l.value < 0)
        OR EXISTS (SELECT 1 FROM public.user_hide_snippets h
                   WHERE h.snippet = a.created_by_snippet))
),
picked AS (
    SELECT
        a.id,
        a.status AS previous_status,
        concat_ws(',',
            CASE WHEN a.id IN (SELECT id FROM k1) THEN 'unsupported_or_negative_fact' END,
            CASE WHEN a.id IN (SELECT id FROM k2) THEN 'no_real_source' END,
            CASE WHEN a.id IN (SELECT id FROM k3) THEN 'created_by_rejected_snippet' END) AS reason,
        p.batch
    FROM active a
    CROSS JOIN params p
    WHERE a.id IN (SELECT id FROM k1 UNION SELECT id FROM k2 UNION SELECT id FROM k3)
),
logged AS (
    INSERT INTO public.kb_deactivation_log (kb_entry, previous_status, reason, batch)
    SELECT id, previous_status, reason, batch FROM picked
    ON CONFLICT (kb_entry, batch) DO NOTHING
    RETURNING kb_entry, reason
),
deactivated AS (
    UPDATE public.kb_entries e
    SET    status              = 'deactivated',
           deactivation_reason = 'cleanup-2026-09: ' || logged.reason,
           updated_at          = now()
    FROM   logged
    WHERE  e.id = logged.kb_entry
      AND  e.status = 'active'
    RETURNING e.id
)
-- hide the embeddings from find_duplicate_kb_entries (see header); reversible in 08
UPDATE public.kb_entry_embeddings kee
SET    status     = 'Deactivated',
       updated_at = now()
FROM   deactivated d
WHERE  kee.kb_entry = d.id
  AND  kee.status = 'Processed';

COMMIT;

-- Verify (read-only):
-- SELECT status, count(*) FROM public.kb_entries GROUP BY status;
-- SELECT reason, count(*) FROM public.kb_deactivation_log WHERE batch = 'cleanup-2026-09-kb' GROUP BY reason ORDER BY 2 DESC;
-- SELECT status, count(*) FROM public.kb_entry_embeddings GROUP BY status;
