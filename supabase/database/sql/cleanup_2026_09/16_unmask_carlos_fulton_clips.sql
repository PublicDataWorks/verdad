-- 16_unmask_carlos_fulton_clips.sql (2026-09-19, applied 20:05 UTC): restore the pre-gate confidence scores of
-- three Radio Mundo (WNMA, Florida) clips from 2026-09-10 07:24-07:27 UTC so they are searchable on verdad.app,
-- per docs/HANDOFF_2026-09-19_carlos_fulton_clips.md and Rajiv's direction ("our system should not hide them,
-- it should analyze them and explain correctly when they are misleading"). Tracking: VER-373, VER-358.
--
-- The evidence gate (apply_evidence_caps, stage_3/models.py) had capped all three at 40 because the verdict is
-- verified_false with no search result marked contradicts_claim. The gate is NOT changed; this is a manual
-- override for exactly these ids. The gate's own record (grounding_metadata.evidence_gate.original_*) supplies
-- the scores that are restored, and an editor's note is prefixed to the explanation in both languages.
-- Re-queuing these rows through Stage 3/4 would cap them again; exclude them from VER-389 batches.
--
-- Note: only 3e53d8e1 had been through Stage 4 review (2026-09-19 19:34 UTC). c253e70f and fb43bf56 were capped by
-- the Stage 3 gate and have reviewed_at NULL, so this puts unreviewed Stage 3 output into the feed at 95; their
-- explanations were regrounded by hand on 2026-09-19 (batch regrounded-2026-09-19-carlos, see VER-373).
--
-- Idempotent: the snapshot insert is skipped if the batch already exists, and the note is not added twice.
--
-- PROVENANCE: after this file and the regrounding recorded in docs/incidents/2026-09-19-carlos-fulton-regrounded-analyses.md
-- (PR #121), these three rows are curated, not pipeline output. Markers: the "Editor's note (2026-09-19)" prefix in
-- explanation, "CORRECTED 2026-09-19 (manual review)" in confidence_scores.analysis.claims, and the two
-- snippet_analysis_snapshot batches. Do not re-queue them; a Stage 3/4 re-run overwrites the curation. If more rows
-- ever need this, add an explicit curated-override marker (column or override table) rather than repeating the pattern.

BEGIN;

INSERT INTO public.snippet_analysis_snapshot
    (snippet, batch, status, title, summary, explanation, disinformation_categories, confidence_scores,
     grounding_metadata, thought_summaries, analyzed_by, reviewed_by, reviewed_at, stage_3_prompt_version_id)
SELECT id, 'unmask-2026-09-19-carlos', status, title, summary, explanation, disinformation_categories,
       confidence_scores, grounding_metadata, thought_summaries, analyzed_by, reviewed_by, reviewed_at,
       stage_3_prompt_version_id
FROM public.snippets
WHERE id IN ('fb43bf56-692d-4a68-8d96-edb029854bd2', 'c253e70f-c00a-4ba2-8e15-bd66cf458574',
             '3e53d8e1-fdbd-4c4c-a692-f34be0b10962')
  AND NOT EXISTS (SELECT 1 FROM public.snippet_analysis_snapshot x
                  WHERE x.snippet = snippets.id AND x.batch = 'unmask-2026-09-19-carlos');

WITH g AS (
    SELECT id, grounding_metadata::jsonb -> 'evidence_gate' AS eg
    FROM public.snippets
    WHERE id IN ('fb43bf56-692d-4a68-8d96-edb029854bd2', 'c253e70f-c00a-4ba2-8e15-bd66cf458574',
                 '3e53d8e1-fdbd-4c4c-a692-f34be0b10962')
)
UPDATE public.snippets s
SET confidence_scores = jsonb_set(jsonb_set(s.confidence_scores, '{overall}', g.eg -> 'original_overall'),
                                  '{categories}', g.eg -> 'original_categories'),
    explanation = jsonb_set(jsonb_set(s.explanation,
        '{english}', to_jsonb('Editor''s note (2026-09-19): VERDAD restored this clip''s original confidence score so journalists can find it. The automated check found no published article specifically contradicting these claims, which is why the pipeline had capped the score at 40; the analysis below explains why the claims are unsupported. ' || (s.explanation ->> 'english'))),
        '{spanish}', to_jsonb('Nota del editor (19-09-2026): VERDAD restauró la puntuación de confianza original de este clip para que los periodistas puedan encontrarlo. La verificación automática no halló ningún artículo publicado que contradiga específicamente estas afirmaciones, motivo por el cual el sistema había limitado la puntuación a 40; el análisis siguiente explica por qué las afirmaciones carecen de sustento. ' || coalesce(s.explanation ->> 'spanish', ''))),
    updated_at = now()
FROM g
WHERE s.id = g.id
  AND g.eg ? 'original_overall' AND g.eg ? 'original_categories'   -- never write NULL scores if the gate record is missing
  AND (s.explanation ->> 'english') NOT LIKE 'Editor''s note (2026-09-19)%';

COMMIT;

-- Verify (as an authenticated user; the three ids should be the newest results at 95):
--   select set_config('request.jwt.claims', '{"sub":"<user uuid>","role":"authenticated"}', true);   -- transaction-local
--   select public.get_snippets('spanish', null, 0, 10, 'latest', 'fulton', true) -> 'num_of_snippets';   -- 50 on 2026-09-19
--
-- ROLLBACK:
--   UPDATE public.snippets s SET confidence_scores = x.confidence_scores, explanation = x.explanation, updated_at = now()
--   FROM public.snippet_analysis_snapshot x WHERE x.snippet = s.id AND x.batch = 'unmask-2026-09-19-carlos';
