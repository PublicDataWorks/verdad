-- Correct a VERDAD snippet's analysis and restore it to verdad.app.
--
-- HOW TO USE
--   1. Copy this file into the scratchpad, never edit it in place.
--   2. Replace every <placeholder>. Set the two \set values at the top once.
--   3. Show the filled file to a human and run it ONLY after they approve.
--      CLAUDE.md requires human confirmation before any UPDATE/DELETE on production.
--   4. Run the verification block at the bottom afterwards.
--
-- ORDER MATTERS: snapshot -> rewrite -> provenance -> unhide -> close queue -> record verdict.
-- The snapshot is the rollback. Do not reorder it later.

\set snippet_id '<snippet-uuid>'
\set batch      'manual-<YYYY-MM-DD>-<short-uuid>'

begin;

-- ---------------------------------------------------------------------------
-- 1. SNAPSHOT (rollback point). Must run before any write.
-- ---------------------------------------------------------------------------
insert into snippet_analysis_snapshot (
    snippet, batch, snapshot_at, status, title, summary, explanation,
    disinformation_categories, confidence_scores, grounding_metadata,
    thought_summaries, analyzed_by, reviewed_by, reviewed_at,
    stage_3_prompt_version_id, labels
)
select s.id, :'batch', now(), s.status, s.title, s.summary, s.explanation,
       s.disinformation_categories, s.confidence_scores, s.grounding_metadata,
       s.thought_summaries, s.analyzed_by, s.reviewed_by, s.reviewed_at,
       s.stage_3_prompt_version_id, null
from snippets s
where s.id = :'snippet_id'::uuid;

-- Abort if the snapshot did not land. Never proceed without a rollback point.
do $$
begin
  if not exists (
    select 1 from snippet_analysis_snapshot
    where snippet = :'snippet_id'::uuid and batch = :'batch'
  ) then
    raise exception 'snapshot missing for % / % -- aborting', :'snippet_id', :'batch';
  end if;
end $$;

-- ---------------------------------------------------------------------------
-- 2. REWRITE THE ANALYSIS
--
-- Stage 4 reviewer 1.3.0 rules (live since 2026-09-22) that this must satisfy:
--   * claims[] holds ONLY claims a retrieved source contradicts; each evidence
--     opens with that source.
--   * A searched-but-empty or never-searched claim gets NO claims[] entry.
--     Name it in explanation and in score_adjustments.adjustment_reason.
--   * The central claim is first in claims[] only when a source contradicts it.
--   * overall is never an average of claims[].score.
--   * Drop any category asserting fabrication ("Fabricated Content") when the
--     verdict rests on nothing retrieved -- the evidence gate reads a category
--     name as a falsity verdict.
--   * A sub-claim verified as GENUINE has no structured home; put it in the
--     explanation prose and say the element is real.
--
-- NOTE: confidence_scores.analysis.explanation is EMPTY on production rows.
--       The prose lives in the top-level explanation jsonb. Edit that.
--
-- PRECEDENCE TRAP: 'x' || to_jsonb(v)->>'k' parses as ('x' || to_jsonb(v))->>'k'.
--                  Always parenthesise: 'x' || (to_jsonb(v)->>'k').
-- ---------------------------------------------------------------------------
update snippets s
set confidence_scores = jsonb_set(
        jsonb_set(
            jsonb_set(
                s.confidence_scores,
                '{analysis,claims}',
                -- Rebuilt claims array. Annotate each hand-touched entry so it
                -- is auditable, e.g. evidence opening with
                --   'CORRECTED <date> (manual review): ...'
                --   'GENUINE (manual review). ...'
                '<corrected-claims-json-array>'::jsonb
            ),
            '{verification_status}',
            to_jsonb('<verified_false|insufficient_evidence|verified_true|uncertain>'::text)
        ),
        '{overall}',
        to_jsonb(<corrected-overall-int>)
    ),

    -- Bilingual prose. Repair mojibake here too (Nicol\b00e1s -> Nicolás) and
    -- re-attribute anything that is the host's phrasing, not our finding.
    explanation = jsonb_build_object(
        'english', '<corrected-english-explanation>',
        'spanish', '<corrected-spanish-explanation>'
    ),

    -- Spanish labels included; repair accents.
    disinformation_categories = '<corrected-categories-array>',

-- ---------------------------------------------------------------------------
-- 3. PROVENANCE. Never leave a hand edit wearing a model's name.
-- ---------------------------------------------------------------------------
    reviewed_by = 'manual-consistency-pass-<YYYY-MM-DD>',
    reviewed_at = now(),
    updated_at  = now()
where s.id = :'snippet_id'::uuid;

-- ---------------------------------------------------------------------------
-- 4. UNHIDE. Scoped to this one snippet -- never a set-based delete.
--    One row here hides the clip from EVERY non-admin viewer, including via
--    its direct URL, because get_snippet/get_public_snippet do not scope the
--    EXISTS check to the caller.
-- ---------------------------------------------------------------------------
delete from user_hide_snippets where snippet = :'snippet_id'::uuid;

-- ---------------------------------------------------------------------------
-- 5. CLOSE THE QUEUE ROW. Note the column is snippet_id here, but `snippet`
--    in user_hide_snippets and snippet_analysis_snapshot. They differ.
-- ---------------------------------------------------------------------------
update downvote_review_queue
set status = 'completed', processed_at = now()
where snippet_id = :'snippet_id'::uuid;

-- ---------------------------------------------------------------------------
-- 6. RECORD THE VERDICT so the reason survives the session.
-- ---------------------------------------------------------------------------
insert into snippet_hide_review (snippet, batch, verdict, why, reviewed_at)
values (
    :'snippet_id'::uuid,
    :'batch',
    'restored',
    '<why: what was wrong with the analysis, what was corrected, what it now rests on>',
    now()
);

commit;

-- ---------------------------------------------------------------------------
-- VERIFY. hide_rows must be 0; overall >= 95 to appear in the feed;
--         reviewed_by must be your marker; queue_status 'completed'.
-- ---------------------------------------------------------------------------
select (select count(*) from user_hide_snippets where snippet = :'snippet_id'::uuid) as hide_rows,
       (select status from downvote_review_queue where snippet_id = :'snippet_id'::uuid) as queue_status,
       (confidence_scores->>'overall')::int        as overall,
       confidence_scores->>'verification_status'   as verification_status,
       reviewed_by,
       to_char(reviewed_at,'YYYY-MM-DD HH24:MI')   as reviewed_at,
       explanation::text ~ '\\b00[0-9a-f]{2}'      as still_has_mojibake
from snippets
where id = :'snippet_id'::uuid;

-- Then open https://verdad.app/snippet/<snippet-uuid> and confirm it renders.

-- ---------------------------------------------------------------------------
-- ROLLBACK, if the correction turns out wrong. Restores from the snapshot.
-- ---------------------------------------------------------------------------
-- begin;
-- update snippets s
-- set status = p.status, title = p.title, summary = p.summary,
--     explanation = p.explanation,
--     disinformation_categories = p.disinformation_categories,
--     confidence_scores = p.confidence_scores,
--     grounding_metadata = p.grounding_metadata,
--     thought_summaries = p.thought_summaries,
--     analyzed_by = p.analyzed_by, reviewed_by = p.reviewed_by,
--     reviewed_at = p.reviewed_at,
--     stage_3_prompt_version_id = p.stage_3_prompt_version_id,
--     updated_at = now()
-- from snippet_analysis_snapshot p
-- where p.snippet = :'snippet_id'::uuid and p.batch = :'batch' and s.id = p.snippet;
-- commit;
