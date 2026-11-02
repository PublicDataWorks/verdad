-- Undo the Stage 4 citation-check cap (CITATION_CHECK_CAPS, on since 2026-09-22) for reviews in a window:
-- restore confidence_scores.overall / categories[].score from stage_4_citation_check.original_*, drop the
-- [Citation check] note from both explanations, and mark the check restored so this is idempotent.
-- Flip the constant off and deploy first, or the next review re-applies the cap.
-- Rows the evidence gate capped first keep 40: their citation-check original_* are already 40 by design.
-- Set the window, dry-run the SELECT, then run the UPDATE.

-- SELECT count(*) FROM public.snippets
-- WHERE reviewed_at >= '2026-09-22 03:00+00' AND reviewed_at < '2026-09-23 00:00+00'
--   AND left(grounding_metadata, 1) = '{'
--   AND (grounding_metadata::jsonb -> 'stage_4_citation_check' ->> 'applied')::boolean
--   AND NOT (grounding_metadata::jsonb -> 'stage_4_citation_check' ? 'restored_at');

UPDATE public.snippets s
SET confidence_scores = jsonb_set(
        jsonb_set(s.confidence_scores, '{overall}', c.check -> 'original_overall'),
        '{categories}',
        COALESCE((
            SELECT jsonb_agg(cat || jsonb_build_object('score', orig -> 'score') ORDER BY i)
            FROM jsonb_array_elements(s.confidence_scores -> 'categories') WITH ORDINALITY AS a(cat, i)
            JOIN jsonb_array_elements(c.check -> 'original_categories') WITH ORDINALITY AS b(orig, j) ON i = j
        ), s.confidence_scores -> 'categories')
    ),
    explanation = s.explanation || jsonb_build_object(
        'english', regexp_replace(s.explanation ->> 'english', '(\n\n)?\[Citation check\][^\n]*$', ''),
        'spanish', regexp_replace(s.explanation ->> 'spanish', '(\n\n)?\[Citation check\][^\n]*$', '')
    ),
    grounding_metadata = jsonb_set(
        s.grounding_metadata::jsonb, '{stage_4_citation_check,restored_at}', to_jsonb(now()::text)
    )::text
FROM (
    SELECT id, grounding_metadata::jsonb -> 'stage_4_citation_check' AS check
    FROM public.snippets
    WHERE reviewed_at >= '2026-09-22 03:00+00' AND reviewed_at < '2026-09-23 00:00+00'
      AND left(grounding_metadata, 1) = '{'
      AND (grounding_metadata::jsonb -> 'stage_4_citation_check' ->> 'applied')::boolean
      AND NOT (grounding_metadata::jsonb -> 'stage_4_citation_check' ? 'restored_at')
) c
WHERE s.id = c.id
  -- jsonb_set is strict (a NULL input nulls the column) and the ordinal join would truncate a longer
  -- categories array, so only rows shaped exactly as the cap left them
  AND jsonb_typeof(c.check -> 'original_overall') = 'number'
  AND jsonb_typeof(s.confidence_scores -> 'categories') = 'array'
  AND jsonb_typeof(c.check -> 'original_categories') = 'array'
  AND jsonb_array_length(s.confidence_scores -> 'categories') = jsonb_array_length(c.check -> 'original_categories')
  AND jsonb_typeof(s.explanation -> 'english') = 'string'
  AND jsonb_typeof(s.explanation -> 'spanish') = 'string';
