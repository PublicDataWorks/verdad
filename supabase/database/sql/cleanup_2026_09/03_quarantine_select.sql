-- cleanup_2026_09 / step 03: candidate selection for snippet quarantine (READ-ONLY).
--
-- This is the exact definition used for the counts in README.md. It changes
-- nothing. 04_quarantine_execute.sql reuses the same CTEs.
--
-- Parameters live in the `params` CTE:
--   anchor    date the 90-day window is measured from (counts were taken with 2026-09-14)
--   slice_lo / slice_hi  optional recorded_at bounds. The full 90-day window does
--             not finish inside the 2-minute statement_timeout on this project
--             when run through the Management API, so run it in 10-day slices
--             (see README.md) and add the slice results together.
--
-- Definitions (verbatim from the review thread):
--   VISIBLE     status = 'Processed' AND not hidden AND recorded_at > anchor - 90 days
--   OVERALL     (confidence_scores->>'overall')::int
--   FAB         a disinformation_categories element ILIKE '%fabricat%' OR title::text ILIKE '%fabricat%'
--   TXT         coalesce(explanation->>'english','') || ' ' || coalesce(confidence_scores::text,'')
--   NO_EVIDENCE TXT ~* <regex below>   (the model itself says it found nothing)
--   DATED_SRC   TXT ~* <regex below>   (a URL or a dated citation is present)
--   HAS_CONTRADICTING_EVIDENCE
--               grounding_metadata parses as a jsonb object (Stage 3 writes
--               verification_evidence there: searches_performed[].results[] with url,
--               relevance_to_claim; Stage 4 overwrites it with kb_research/web_research
--               PROSE strings, which count as no structured evidence) and at least one
--               result has a non-empty http(s) url and relevance_to_claim =
--               'contradicts_claim', or, when relevance_to_claim is missing, its search
--               has result_status = 'results_found'
--               Measured 2026-09-14: Stage 4 runs on every snippet before it becomes
--               'Processed' and overwrites the Stage 3 search log with prose, so only
--               14 of 1,530 broad rows from the last 10 days still carry the structured
--               shape, and the check currently excludes 0 rows. It is kept because it
--               is the correct guard whenever the structured evidence is present, and
--               it becomes effective as soon as Stage 4 stops overwriting the column.
--   NARROW_A    VISIBLE AND OVERALL >= 95 AND FAB AND NO_EVIDENCE AND NOT DATED_SRC
--                 AND NOT HAS_CONTRADICTING_EVIDENCE
--                 reason 'unsupported_fabrication_claim'
--                 (the text heuristics say the model found nothing; the evidence check
--                 makes sure its structured search log agrees, so a correctly
--                 verified-false snippet with tier-1 sources is not quarantined)
--   NARROW_B    VISIBLE AND OVERALL >= 70 AND confidence_scores->>'verification_status'
--                 IN ('insufficient_evidence','uncertain')
--                 reason 'insufficient_evidence_high_score'
--   NARROW      NARROW_A UNION NARROW_B
--   BROAD       VISIBLE AND OVERALL >= 95 AND FAB      reason 'fabrication_label'
--
-- Note: verification_status is a key inside the confidence_scores jsonb, not a
-- column on snippets. disinformation_categories is jsonb[]; d::text keeps the
-- surrounding quotes, which does not affect an ILIKE '%fabricat%' match.

WITH params AS (
    SELECT
        DATE '2026-09-14'                                  AS anchor,
        (DATE '2026-09-14' - INTERVAL '90 days')::timestamptz AS slice_lo,   -- narrow these two to slice
        (DATE '2026-09-14' + INTERVAL '1 day')::timestamptz   AS slice_hi
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
),
flagged AS MATERIALIZED (
    SELECT
        v.*,
        (v.overall >= 95 AND v.fab
            AND v.txt ~*  pt.no_evidence
            AND v.txt !~* pt.dated_src)                                            AS narrow_a_text,
        (v.overall >= 70 AND v.verification_status IN ('insufficient_evidence', 'uncertain')) AS narrow_b,
        (v.overall >= 95 AND v.fab)                                                AS broad
    FROM visible v
    CROSS JOIN patterns pt
),
-- Structured evidence check, evaluated only for rows that need it (f.broad).
-- pg_input_is_valid (PG16+) keeps a non-JSON value from raising; CASE keeps the
-- cast from running on it. Stage 4's prose strings never have searches_performed,
-- so they yield false.
evidence AS (
    SELECT
        f.*,
        coalesce(ev.has_contradicting_evidence, false) AS has_contradicting_evidence
    FROM flagged f
    LEFT JOIN LATERAL (
        SELECT EXISTS (
            SELECT 1
            FROM jsonb_array_elements(
                     CASE WHEN jsonb_typeof(doc.j->'searches_performed') = 'array'
                          THEN doc.j->'searches_performed' ELSE '[]'::jsonb END) sp
            CROSS JOIN LATERAL jsonb_array_elements(
                     CASE WHEN jsonb_typeof(sp->'results') = 'array'
                          THEN sp->'results' ELSE '[]'::jsonb END) r
            WHERE coalesce(r->>'url', '') ~* '^https?://'
              AND (r->>'relevance_to_claim' = 'contradicts_claim'
                   OR (r->>'relevance_to_claim' IS NULL AND sp->>'result_status' = 'results_found'))
        ) AS has_contradicting_evidence
        FROM public.snippets s2
        CROSS JOIN LATERAL (
            SELECT CASE WHEN s2.grounding_metadata IS NOT NULL
                          AND pg_input_is_valid(s2.grounding_metadata, 'jsonb')
                        THEN s2.grounding_metadata::jsonb END AS j
        ) doc
        WHERE s2.id = f.id
          AND f.broad
    ) ev ON true
),
candidates AS (
    SELECT
        f.id,
        f.recorded_at,
        f.overall,
        f.narrow_a_text,
        f.has_contradicting_evidence,
        (f.narrow_a_text AND NOT f.has_contradicting_evidence) AS narrow_a,
        f.narrow_b,
        f.broad,
        -- reason tags exactly as they will be written to snippet_quarantine_log.reason
        concat_ws(',',
            CASE WHEN f.narrow_a_text AND NOT f.has_contradicting_evidence THEN 'unsupported_fabrication_claim' END,
            CASE WHEN f.narrow_b THEN 'insufficient_evidence_high_score' END) AS narrow_reason,
        CASE WHEN f.broad THEN 'fabrication_label' END                       AS broad_reason
    FROM evidence f
)
-- Summary counts (what README.md reports). Swap the final SELECT for
--   SELECT * FROM candidates WHERE narrow_a OR narrow_b ORDER BY recorded_at DESC
-- to list the rows themselves.
SELECT
    (SELECT slice_lo FROM params)                          AS slice_lo,
    (SELECT slice_hi FROM params)                          AS slice_hi,
    count(*) FILTER (WHERE overall >= 95)                  AS feed_visible,   -- what get_snippets shows today
    count(*) FILTER (WHERE broad)                          AS broad,
    count(*) FILTER (WHERE broad AND has_contradicting_evidence) AS broad_with_contradicting_evidence,
    count(*) FILTER (WHERE narrow_a_text)                  AS narrow_a_text_only,   -- before the evidence check
    count(*) FILTER (WHERE narrow_a_text AND has_contradicting_evidence) AS narrow_a_excluded_by_evidence,
    count(*) FILTER (WHERE narrow_a)                       AS narrow_a,
    count(*) FILTER (WHERE narrow_b)                       AS narrow_b,
    count(*) FILTER (WHERE narrow_a AND narrow_b)          AS narrow_both,
    count(*) FILTER (WHERE narrow_a OR narrow_b)           AS narrow_union
FROM candidates;
