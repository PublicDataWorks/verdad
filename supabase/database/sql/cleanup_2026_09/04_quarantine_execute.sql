-- cleanup_2026_09 / step 04: quarantine ONE BATCH of up to 2,000 snippets (WRITES).
--
-- Do not run until Rajiv has approved the counts from 03 in Slack, and
-- 01 (enum value) and 02 (log table) have been applied and committed.
--
-- What it does, atomically:
--   1. picks the next <= 2,000 candidates (newest recorded_at first) that are
--      still 'Processed' and NOT yet logged for this batch  -> idempotent
--   2. inserts one snippet_quarantine_log row per snippet (previous_status,
--      reason tags, batch)
--   3. sets snippets.status = 'Quarantined' for exactly those rows
--
-- Repeat the whole file until the UPDATE reports 0 rows. Roughly:
--   narrow ~7,900 rows -> 4 runs;  broad ~11,900 rows -> 6 runs.
-- Keep LIMIT at 2,000 (or lower it) so each run stays inside the 2-minute
-- statement_timeout; the regex filter is the expensive part. If a run still
-- times out, narrow slice_lo/slice_hi to a 10-day window as in step 03.
--
-- Choose the batch by editing `params.batch`:
--   'cleanup-2026-09-narrow'  NARROW_A UNION NARROW_B  (reasons
--                             'unsupported_fabrication_claim' / 'insufficient_evidence_high_score')
--   'cleanup-2026-09-broad'   BROAD                    (reason 'fabrication_label')
-- Run the narrow batch first if both are approved. Because the selection
-- requires status = 'Processed', snippets already quarantined by an earlier
-- batch are not re-logged under the later batch; each log row belongs to the
-- batch that actually moved the snippet, and 05 restores per batch.
--
-- The Supabase SQL editor already wraps a run in a transaction; the explicit
-- BEGIN/COMMIT below is for psql / Management API use and is harmless in the editor.

BEGIN;

WITH params AS (
    SELECT
        'cleanup-2026-09-narrow'::text                        AS batch,       -- <- edit: -narrow or -broad
        DATE '2026-09-14'                                     AS anchor,      -- same anchor as step 03
        (DATE '2026-09-14' - INTERVAL '90 days')::timestamptz AS slice_lo,
        (DATE '2026-09-14' + INTERVAL '1 day')::timestamptz   AS slice_hi,
        2000                                                  AS batch_size
),
patterns AS (
    SELECT
        '(no|zero|absence of any) (credible |verifiable |public |official |online |such )?(evidence|records?|results?|reports?|information|mention|trace)|does not exist|do not exist|non-?existent|never (happened|occurred|existed|took place)|did not (happen|occur|take place)|yield(ed|s)? no|no search results' AS no_evidence,
        'https?://|(January|February|March|April|May|June|July|August|September|October|November|December) [0-9]{1,2},? 20[0-9]{2}|[0-9]{1,2} de (enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre) de 20[0-9]{2}|20[0-9]{2}-[0-9]{2}-[0-9]{2}' AS dated_src
),
visible AS (
    SELECT
        s.id,
        s.recorded_at,
        s.status,
        (s.confidence_scores->>'overall')::int                         AS overall,
        s.confidence_scores->>'verification_status'                    AS verification_status,
        (EXISTS (SELECT 1 FROM unnest(s.disinformation_categories) d WHERE d::text ILIKE '%fabricat%')
         OR s.title::text ILIKE '%fabricat%')                          AS fab,
        coalesce(s.explanation->>'english', '') || ' ' || coalesce(s.confidence_scores::text, '') AS txt
    FROM public.snippets s
    CROSS JOIN params p
    WHERE s.status = 'Processed'
      AND NOT EXISTS (SELECT 1 FROM public.user_hide_snippets h WHERE h.snippet = s.id)
      AND s.recorded_at > p.anchor - INTERVAL '90 days'
      AND s.recorded_at >= p.slice_lo
      AND s.recorded_at <  p.slice_hi
      -- idempotency: skip anything already logged for this batch
      AND NOT EXISTS (SELECT 1 FROM public.snippet_quarantine_log l
                      WHERE l.snippet = s.id AND l.batch = p.batch)
),
flagged AS (
    SELECT
        v.*,
        (v.overall >= 95 AND v.fab
            AND v.txt ~*  pt.no_evidence
            AND v.txt !~* pt.dated_src)                                            AS narrow_a,
        (v.overall >= 70 AND v.verification_status IN ('insufficient_evidence', 'uncertain')) AS narrow_b,
        (v.overall >= 95 AND v.fab)                                                AS broad
    FROM visible v
    CROSS JOIN patterns pt
),
picked AS (
    SELECT
        f.id,
        f.status AS previous_status,
        CASE p.batch
            WHEN 'cleanup-2026-09-narrow' THEN
                concat_ws(',',
                    CASE WHEN f.narrow_a THEN 'unsupported_fabrication_claim' END,
                    CASE WHEN f.narrow_b THEN 'insufficient_evidence_high_score' END)
            WHEN 'cleanup-2026-09-broad' THEN 'fabrication_label'
        END AS reason,
        p.batch
    FROM flagged f
    CROSS JOIN params p
    WHERE (p.batch = 'cleanup-2026-09-narrow' AND (f.narrow_a OR f.narrow_b))
       OR (p.batch = 'cleanup-2026-09-broad'  AND f.broad)
    ORDER BY f.recorded_at DESC
    LIMIT (SELECT batch_size FROM params)
),
logged AS (
    INSERT INTO public.snippet_quarantine_log (snippet, previous_status, reason, batch)
    SELECT id, previous_status, reason, batch FROM picked
    ON CONFLICT (snippet, batch) DO NOTHING
    RETURNING snippet
)
UPDATE public.snippets s
SET    status = 'Quarantined'
FROM   logged
WHERE  s.id = logged.snippet
  AND  s.status = 'Processed';   -- never overwrite a status that changed under us

COMMIT;

-- Progress check (read-only), run after each batch:
-- SELECT batch, count(*) AS quarantined, count(*) FILTER (WHERE restored_at IS NOT NULL) AS restored
-- FROM public.snippet_quarantine_log GROUP BY batch;
