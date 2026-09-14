-- cleanup_2026_09 / step 06: candidate selection for knowledge-base deactivation (READ-ONLY).
--
-- Exact definition used for the counts in README.md. Changes nothing;
-- 07_kb_deactivate_execute.sql reuses these CTEs.
--
--   K1  active entries whose (fact || ' ' || coalesce(related_claim,'')) matches
--       NO_EVIDENCE (same regex as step 03) or 'fabricat|fictional|ficticio|never existed|does not exist|no existe'
--       -> the "fact" is really a statement that something has no evidence / is fabricated
--       reason 'unsupported_or_negative_fact'
--   K2  active entries with NO kb_entry_sources row whose url ~* '^https?://' and is not a
--       placeholder (example.com, web_research.com, google.com/search)
--       reason 'no_real_source'
--   K3  active entries whose created_by_snippet is disliked (user_like_snippets.value < 0)
--       or hidden (user_hide_snippets)
--       reason 'created_by_rejected_snippet'
--   Target set = K1 UNION K2 UNION K3 (an entry can carry several reason tags).
--
-- Downstream effect on retrieval:
--   * search_kb_entries (supabase/database/sql/search_kb_entries.sql) joins
--     kb_entry_embeddings to kb_entries and filters ke.status = 'active' AND
--     kee.status = 'Processed', so deactivated entries drop out of RAG retrieval
--     with no further change.
--   * find_duplicate_kb_entries (find_duplicate_kb_entries.sql) has NO
--     kb_entries.status filter; it relies on embeddings of deactivated entries
--     having been deleted by the pipeline, and only filters kee.status = 'Processed'.
--     Step 07 therefore also sets kb_entry_embeddings.status = 'Deactivated' for
--     the affected entries (kee.status is free TEXT) instead of deleting the rows,
--     and step 08 flips it back to 'Processed'. No re-embedding is needed on rollback.

WITH patterns AS (
    SELECT
        '(no|zero|absence of any) (credible |verifiable |public |official |online |such )?(evidence|records?|results?|reports?|information|mention|trace)|does not exist|do not exist|non-?existent|never (happened|occurred|existed|took place)|did not (happen|occur|take place)|yield(ed|s)? no|no search results' AS no_evidence,
        'fabricat|fictional|ficticio|never existed|does not exist|no existe' AS negative_fact
),
active AS (
    SELECT e.id, e.status, e.fact || ' ' || coalesce(e.related_claim, '') AS txt, e.created_by_snippet
    FROM public.kb_entries e
    WHERE e.status = 'active'
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
candidates AS (
    SELECT
        a.id,
        a.status AS previous_status,
        -- reason tags exactly as written to kb_deactivation_log.reason / kb_entries.deactivation_reason
        concat_ws(',',
            CASE WHEN a.id IN (SELECT id FROM k1) THEN 'unsupported_or_negative_fact' END,
            CASE WHEN a.id IN (SELECT id FROM k2) THEN 'no_real_source' END,
            CASE WHEN a.id IN (SELECT id FROM k3) THEN 'created_by_rejected_snippet' END) AS reason
    FROM active a
    WHERE a.id IN (SELECT id FROM k1 UNION SELECT id FROM k2 UNION SELECT id FROM k3)
)
-- Summary counts (what README.md reports). Swap for
--   SELECT * FROM candidates ORDER BY reason
-- to list the rows.
SELECT
    (SELECT count(*) FROM k1)         AS k1,
    (SELECT count(*) FROM k2)         AS k2,
    (SELECT count(*) FROM k3)         AS k3,
    (SELECT count(*) FROM candidates) AS total_union,
    (SELECT count(*) FROM active)     AS active_total;
