-- cleanup_2026_09 / step 04b: snapshot the current analysis of every quarantined snippet (WRITES, audit only).
--
-- Run after 04 has finished for a batch and BEFORE 09 re-queues anything from
-- that batch. Reprocessing overwrites title/summary/explanation/categories/
-- confidence_scores/grounding_metadata on the snippet row; this table keeps
-- the pre-cleanup analysis so before/after can be compared and a wrong
-- reprocessing result can be reviewed against what the public saw.
--
-- One row per (snippet, batch): every snippet_quarantine_log row for the batch
-- (restored or not) gets a snapshot. Idempotent: rows already present are
-- skipped (NOT EXISTS + ON CONFLICT DO NOTHING). 2,000 per run, newest
-- recorded_at first; repeat until the INSERT reports 0 rows. Guard before 09:
--   snapshot count for the batch = log count for the batch  (query in README.md).
--
-- Audit table: no foreign keys (rows must outlive the snippet), RLS on with no
-- policies, service_role grant — same pattern as the two log tables.

-- ---------- Section A: table (once) ----------
CREATE TABLE IF NOT EXISTS public.snippet_analysis_snapshot (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    snippet                     UUID NOT NULL,          -- no FK on purpose (audit)
    batch                       TEXT NOT NULL,
    snapshot_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    status                      public.processing_status,
    title                       JSONB,
    summary                     JSONB,
    explanation                 JSONB,
    disinformation_categories   JSONB[],
    confidence_scores           JSONB,
    grounding_metadata          TEXT,
    thought_summaries           TEXT,
    analyzed_by                 TEXT,
    reviewed_by                 TEXT,
    reviewed_at                 TIMESTAMPTZ,
    stage_3_prompt_version_id   UUID,
    labels                      JSONB NOT NULL DEFAULT '[]'::jsonb,
        -- array of {label_id, text, is_ai_suggested, applied_by, upvote_count}
        -- from snippet_labels JOIN labels at snapshot time
    UNIQUE (snippet, batch)
);

COMMENT ON TABLE public.snippet_analysis_snapshot IS
    'cleanup_2026_09: pre-reprocessing copy of each quarantined snippet''s analysis and labels, per batch.';

CREATE INDEX IF NOT EXISTS idx_snippet_analysis_snapshot_snippet
    ON public.snippet_analysis_snapshot (snippet);
CREATE INDEX IF NOT EXISTS idx_snippet_analysis_snapshot_batch
    ON public.snippet_analysis_snapshot (batch);

ALTER TABLE public.snippet_analysis_snapshot ENABLE ROW LEVEL SECURITY;
-- No policies on purpose: service_role only.
GRANT ALL ON TABLE public.snippet_analysis_snapshot TO service_role;

-- ---------- Section B: one 2,000-row snapshot batch (repeat until 0 rows) ----------
BEGIN;

WITH params AS (
    SELECT 'cleanup-2026-09-narrow'::text AS batch,   -- <- edit: -narrow or -broad
           2000                          AS batch_size
),
todo AS (
    SELECT s.*, p.batch
    FROM public.snippet_quarantine_log l
    JOIN public.snippets s ON s.id = l.snippet
    CROSS JOIN params p
    WHERE l.batch = p.batch
      AND NOT EXISTS (SELECT 1 FROM public.snippet_analysis_snapshot x
                      WHERE x.snippet = l.snippet AND x.batch = l.batch)
    ORDER BY s.recorded_at DESC
    LIMIT (SELECT batch_size FROM params)
)
INSERT INTO public.snippet_analysis_snapshot (
    snippet, batch, status, title, summary, explanation, disinformation_categories,
    confidence_scores, grounding_metadata, thought_summaries, analyzed_by,
    reviewed_by, reviewed_at, stage_3_prompt_version_id, labels)
SELECT
    t.id, t.batch, t.status, t.title, t.summary, t.explanation, t.disinformation_categories,
    t.confidence_scores, t.grounding_metadata, t.thought_summaries, t.analyzed_by,
    t.reviewed_by, t.reviewed_at, t.stage_3_prompt_version_id,
    coalesce(lb.labels, '[]'::jsonb)
FROM todo t
LEFT JOIN LATERAL (
    SELECT jsonb_agg(jsonb_build_object(
               'label_id',        l.id,
               'text',            l.text,
               'is_ai_suggested', l.is_ai_suggested,
               'applied_by',      sl.applied_by,
               'upvote_count',    sl.upvote_count)
           ORDER BY sl.created_at) AS labels
    FROM public.snippet_labels sl
    JOIN public.labels l ON l.id = sl.label
    WHERE sl.snippet = t.id
) lb ON true
ON CONFLICT (snippet, batch) DO NOTHING;

COMMIT;

-- Guard before running 09 for the batch (must return equal = true):
-- SELECT l.batch, l.n AS logged, coalesce(x.n, 0) AS snapshotted, l.n = coalesce(x.n, 0) AS equal
-- FROM (SELECT batch, count(*) n FROM public.snippet_quarantine_log GROUP BY batch) l
-- LEFT JOIN (SELECT batch, count(*) n FROM public.snippet_analysis_snapshot GROUP BY batch) x USING (batch);
