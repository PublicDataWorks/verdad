-- 14_seed_corrections.sql (2026-09-18): corrections to the 11_seed_dated_facts.sql rows that were applied to
-- production on 2026-09-17 20:35 UTC, from the CodeRabbit review of PR #98 and the Opus review of PR #107.
-- Idempotent; each statement is a no-op once applied. Tracking: VER-326, VER-375.
--
-- 1. Vatican News article: publication date was recorded as 2026-08-01; the article metadata says 2026-08-07.
-- 2. Fact 8 combined the Flávio Bolsonaro candidacy (sources typed 'other') with the Lula-Trump meeting (PBS,
--    tier2). select_trustworthy_entries judges the whole entry, so the candidacy assertion inherited PBS's
--    standing. Split: the existing entry keeps only the meeting and the PBS source and takes 8b's score and
--    categories; a new entry carries the candidacy with its two 'other' sources (context only until a
--    tier1/tier2 source is attached).
-- 3. The rewritten meeting entry was embedded on 2026-09-17 from the combined text. That embedding is deleted
--    here so the backfill (backfill_kb_embeddings.py, paged per VER-377) re-embeds the new text; the backfill
--    only ever embeds entries with no embedding row, so without this delete the stale vector would stay forever.
--
-- If the combined row was already split by a run of the updated 11_seed_dated_facts.sql (which inserts 8a and
-- 8b separately), `candidacy` resolves to the existing 8a row instead of inserting, so the sources still move
-- and the combined row is still rewritten rather than left half-applied.

BEGIN;

UPDATE public.kb_entry_sources
SET publication_date = '2026-08-07'::date
WHERE url = 'https://www.vaticannews.va/en/pope/news/2026-08/pope-leos-packed-schedule-4-day-apostolic-journey-to-france.html'
  AND publication_date = '2026-08-01'::date;

WITH combined AS (
    SELECT id FROM public.kb_entries
    WHERE created_by_model = 'analyst-seed-2026-09-17'
      AND fact = 'Flávio Bolsonaro is a candidate in Brazil''s 2026-10-04 presidential election and on 2026-08-05 named federal deputy Alfredo Gaspar as his running mate; Luiz Inácio Lula da Silva is the incumbent president. Lula met President Trump at the White House in the week of 2026-05-07.'
),
candidacy_new AS (
    INSERT INTO public.kb_entries (fact, related_claim, confidence_score, disinformation_categories, keywords, is_time_sensitive, valid_from, status, created_by_model)
    SELECT 'Flávio Bolsonaro is a candidate in Brazil''s 2026-10-04 presidential election and on 2026-08-05 named federal deputy Alfredo Gaspar as his running mate; Luiz Inácio Lula da Silva is the incumbent president.', 'Flávio Bolsonaro is not a presidential candidate', 85, ARRAY['Political Figures and Movements','Election Integrity and Voting Processes'], ARRAY['Flávio Bolsonaro','Brazil','2026 election','Lula','Alfredo Gaspar'], false, '2026-08-05'::timestamptz, 'active', 'analyst-seed-2026-09-17'
    FROM combined
    WHERE NOT EXISTS (SELECT 1 FROM public.kb_entries WHERE created_by_model = 'analyst-seed-2026-09-17' AND fact LIKE 'Flávio Bolsonaro is a candidate in Brazil''s 2026-10-04 presidential election%incumbent president.')
    RETURNING id
),
-- Exactly one row when `combined` matched: the row just inserted, or the pre-existing 8a (the SELECT sees the
-- pre-statement snapshot, so it never double-counts the insert).
candidacy AS (
    SELECT id FROM candidacy_new
    UNION ALL
    SELECT e.id FROM public.kb_entries e, combined
    WHERE e.created_by_model = 'analyst-seed-2026-09-17'
      AND e.fact LIKE 'Flávio Bolsonaro is a candidate in Brazil''s 2026-10-04 presidential election%incumbent president.'
),
moved AS (
    UPDATE public.kb_entry_sources s
    SET kb_entry = (SELECT id FROM candidacy LIMIT 1)
    FROM combined c
    WHERE s.kb_entry = c.id
      AND s.source_type = 'other'
      AND EXISTS (SELECT 1 FROM candidacy)
    RETURNING s.id
)
UPDATE public.kb_entries e
SET fact = 'Brazilian President Luiz Inácio Lula da Silva met President Trump at the White House in the week of 2026-05-07.',
    related_claim = 'Trump never met Lula',
    confidence_score = 95,
    disinformation_categories = ARRAY['Political Figures and Movements'],
    keywords = ARRAY['Lula','Trump','White House','Brazil'],
    valid_from = '2026-05-07'::timestamptz
FROM combined c
WHERE e.id = c.id
  AND EXISTS (SELECT 1 FROM candidacy);

-- Drop the stale embedding of the rewritten entry (see note 3). Guarded on the embedded text, so once the
-- backfill has re-embedded the meeting-only text this matches nothing.
DELETE FROM public.kb_entry_embeddings emb
USING public.kb_entries e
WHERE emb.kb_entry = e.id
  AND e.created_by_model = 'analyst-seed-2026-09-17'
  AND e.fact = 'Brazilian President Luiz Inácio Lula da Silva met President Trump at the White House in the week of 2026-05-07.'
  AND emb.embedded_document LIKE '%Flávio Bolsonaro%';

COMMIT;

-- Afterwards: run the paged embedding backfill (VER-375/VER-377) so both the new candidacy entry and the
-- rewritten meeting entry get embeddings.
-- Verify:
-- SELECT e.fact, e.confidence_score, e.disinformation_categories, count(s.id) AS sources,
--        (SELECT count(*) FROM public.kb_entry_embeddings x WHERE x.kb_entry = e.id) AS embeddings
--   FROM public.kb_entries e LEFT JOIN public.kb_entry_sources s ON s.kb_entry = e.id
--   WHERE e.created_by_model = 'analyst-seed-2026-09-17' AND (e.fact LIKE 'Flávio Bolsonaro%' OR e.fact LIKE 'Brazilian President%')
--   GROUP BY 1, 2, 3;                     -- candidacy: 85, 2 sources; meeting: 95, 1 source; embeddings 0 until the backfill runs
-- SELECT publication_date FROM public.kb_entry_sources WHERE url LIKE '%pope-leos-packed-schedule%';   -- 2026-08-07
