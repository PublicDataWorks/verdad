-- cleanup_2026_09 / step 06: candidate selection for knowledge-base deactivation (READ-ONLY).
--
-- Exact definition used for the counts in README.md. Changes nothing;
-- 07_kb_deactivate_execute.sql reuses these CTEs.
--
--   K1  active entries whose (fact || ' ' || coalesce(related_claim,'')) matches
--       NO_EVIDENCE (same regex as step 03) or 'fabricat|fictional|ficticio|never existed|does not exist|no existe'
--       -> the "fact" is really a statement that something has no evidence / is fabricated.
--       These negation facts are the self-poisoning mechanism itself: they encode
--       "we found nothing" as a permanent truth with no expiry, and RAG then tells the
--       model that the real event (e.g. the election of Pope Leo XIV) never happened.
--       K1 is therefore a class-level deactivation, run as ITS OWN BATCH
--       ('cleanup-2026-09-kb-negation') so it is approved as a distinct decision.
--       EXCEPTION (kept active): a K1 entry whose fact text contains an explicit date
--       (the DATED_SRC date patterns) AND that has at least one source whose host is a
--       fact-checker / wire service on the allowlist below. Those are properly
--       sourced, dated fact-checks and stay.
--       reason 'unsupported_or_negative_fact'
--   K2  active entries with NO kb_entry_sources row whose url ~* '^https?://' and is not a
--       placeholder (example.com, web_research.com, google.com/search)
--       reason 'no_real_source'
--   K3  active entries whose created_by_snippet is disliked (user_like_snippets.value < 0)
--       or hidden (user_hide_snippets)
--       reason 'created_by_rejected_snippet'
--   Batches:
--     'cleanup-2026-09-kb-negation'  = K1 minus the exception
--     'cleanup-2026-09-kb-unsourced' = K2 UNION K3
--   An entry in both carries every matching reason tag and is logged under whichever
--   batch runs first (07 only touches status = 'active').
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
        'fabricat|fictional|ficticio|never existed|does not exist|no existe' AS negative_fact,
        -- date patterns of DATED_SRC (step 03) without the URL alternative
        '(January|February|March|April|May|June|July|August|September|October|November|December) [0-9]{1,2},? 20[0-9]{2}|[0-9]{1,2} de (enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre) de 20[0-9]{2}|20[0-9]{2}-[0-9]{2}-[0-9]{2}' AS explicit_date,
        -- fact-checker / wire-service hosts (any subdomain) that exempt a dated K1 entry
        '^https?://([a-z0-9-]+\.)*(reuters\.com|apnews\.com|bbc\.com|bbc\.co\.uk|politifact\.com|factcheck\.org|snopes\.com|afp\.com|factuel\.afp\.com|verificat\.cat|maldita\.es|newtral\.es|efe\.com|chequeado\.com|animalpolitico\.com|elsurti\.com)(/|$)' AS trusted_host
),
active AS (
    SELECT e.id, e.status, e.fact, e.fact || ' ' || coalesce(e.related_claim, '') AS txt, e.created_by_snippet
    FROM public.kb_entries e
    WHERE e.status = 'active'
),
k1_raw AS (
    SELECT a.id FROM active a CROSS JOIN patterns pt
    WHERE a.txt ~* pt.no_evidence OR a.txt ~* pt.negative_fact
),
k1_exception AS (
    SELECT a.id FROM active a CROSS JOIN patterns pt
    WHERE a.id IN (SELECT id FROM k1_raw)
      AND a.fact ~* pt.explicit_date
      AND EXISTS (SELECT 1 FROM public.kb_entry_sources s
                  WHERE s.kb_entry = a.id AND s.url ~* pt.trusted_host)
),
k1 AS (
    SELECT id FROM k1_raw EXCEPT SELECT id FROM k1_exception
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
-- to list the rows, or
--   SELECT a.* FROM active a WHERE a.id IN (SELECT id FROM k1_exception)
-- to review the kept fact-checks.
SELECT
    (SELECT count(*) FROM k1_raw)       AS k1_raw,
    (SELECT count(*) FROM k1_exception) AS k1_exception_kept,
    (SELECT count(*) FROM k1)           AS k1_negation_batch,
    (SELECT count(*) FROM k2)           AS k2,
    (SELECT count(*) FROM k3)           AS k3,
    (SELECT count(*) FROM (SELECT id FROM k2 UNION SELECT id FROM k3) u) AS unsourced_batch,
    (SELECT count(*) FROM candidates)   AS total_union,
    (SELECT count(*) FROM active)       AS active_total;
