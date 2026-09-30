-- Correct a VERDAD snippet's analysis and restore it to verdad.app.
--
-- HOW TO USE
--   1. Copy this file into the scratchpad, never edit it in place.
--   2. Replace every <placeholder>. Set the two \set values at the top once.
--   3. Show the filled file to a human and run it ONLY after they approve.
--      CLAUDE.md requires human confirmation before any UPDATE/DELETE on production.
--   4. Run the verification block at the bottom afterwards.
--
-- PRECONDITION this file assumes, and asserts in the guard below:
--   the snippet currently has at least one user_hide_snippets row.
-- The rollback block relies on that assertion to restore visibility correctly.
-- If the snippet is NOT hidden, you are not doing an unhide; stop and re-read
-- step 1 of SKILL.md.
--
-- ORDER MATTERS: snapshot -> assert -> rewrite -> provenance -> unhide ->
--                close queue -> record verdict. The snapshot is the rollback.

\set snippet_id '<snippet-uuid>'
\set batch      'manual-<YYYY-MM-DD>-<short-uuid>'

begin;

-- psql does NOT interpolate :'var' inside dollar-quoted bodies ($$ ... $$), so
-- the values are published as transaction-local settings and read back with
-- current_setting() inside the PL/pgSQL guard. Setting them here, inside the
-- transaction, with is_local => true, means they vanish on commit or rollback.
select set_config('verdad.snippet_id', :'snippet_id', true),
       set_config('verdad.batch',      :'batch',      true);

-- ---------------------------------------------------------------------------
-- 1. SNAPSHOT (rollback point). Must run before any write.
--
-- `labels` is NOT NULL DEFAULT '[]'::jsonb. An explicit NULL does NOT fall back
-- to the default, it violates the constraint, so the column is omitted here and
-- takes its default. Consequence to know: label associations are NOT captured,
-- so the rollback restores the analysis and visibility but not labels. If a
-- correction also changes labels, snapshot them separately first.
-- ---------------------------------------------------------------------------
insert into snippet_analysis_snapshot (
    snippet, batch, snapshot_at, status, title, summary, explanation,
    disinformation_categories, confidence_scores, grounding_metadata,
    thought_summaries, analyzed_by, reviewed_by, reviewed_at,
    stage_3_prompt_version_id
)
select s.id, :'batch', now(), s.status, s.title, s.summary, s.explanation,
       s.disinformation_categories, s.confidence_scores, s.grounding_metadata,
       s.thought_summaries, s.analyzed_by, s.reviewed_by, s.reviewed_at,
       s.stage_3_prompt_version_id
from snippets s
where s.id = :'snippet_id'::uuid;

-- ---------------------------------------------------------------------------
-- 2. ASSERT. No rollback point, or a snippet that was not hidden, aborts here.
-- ---------------------------------------------------------------------------
do $guard$
declare
    v_snippet uuid := current_setting('verdad.snippet_id')::uuid;
    v_batch   text := current_setting('verdad.batch');
    v_hides   int;
begin
    if not exists (
        select 1 from snippet_analysis_snapshot
        where snippet = v_snippet and batch = v_batch
    ) then
        raise exception 'snapshot missing for % / % -- aborting', v_snippet, v_batch;
    end if;

    select count(*) into v_hides from user_hide_snippets where snippet = v_snippet;
    if v_hides = 0 then
        raise exception
            'snippet % has no hide row; this template is for unhiding. Re-read step 1.',
            v_snippet;
    end if;
end
$guard$;

-- ---------------------------------------------------------------------------
-- 3. REWRITE THE ANALYSIS
--
-- Categories live in TWO places and must be corrected together, or the restored
-- snippet carries contradictory verdict data:
--   * disinformation_categories  -- the array column
--   * confidence_scores.categories -- a jsonb array copy
-- score_adjustments must also be refreshed when the claims change, or the
-- adjustment_reason still describes the old verdict.
--
-- Stage 4 reviewer 1.3.0 rules (live since 2026-09-22, VER-391):
--   * claims[] holds ONLY claims a retrieved source contradicts; each evidence
--     opens with that source.
--   * A searched-but-empty or never-searched claim gets NO claims[] entry.
--     Name it in explanation and in score_adjustments.adjustment_reason.
--   * The central claim is first in claims[] only when a source contradicts it.
--   * overall is never an average of claims[].score.
--   * Drop any category asserting fabrication ("Fabricated Content" /
--     "Contenido Fabricado") when the verdict rests on nothing retrieved -- the
--     evidence gate reads a category name as a falsity verdict. Drop it from
--     BOTH category fields.
--   * Score ceiling 40 for an unsupported verdict is a ceiling, not a target.
--   * A sub-claim verified as GENUINE has no structured home under 1.3.0; put it
--     in the explanation prose and say the element is real.
--
-- NOTE: confidence_scores.analysis.explanation is EMPTY on production rows.
--       The prose lives in the top-level explanation jsonb. Edit that.
--
-- PRECEDENCE TRAP: 'x' || to_jsonb(v)->>'k' parses as ('x' || to_jsonb(v))->>'k'.
--                  Always parenthesise: 'x' || (to_jsonb(v)->>'k').
-- ---------------------------------------------------------------------------
update snippets s
set confidence_scores =
        jsonb_set(
        jsonb_set(
        jsonb_set(
        jsonb_set(
        jsonb_set(
            s.confidence_scores,
            -- Rebuilt claims array. Annotate each hand-touched entry so it is
            -- auditable, e.g. evidence opening with
            --   'CORRECTED <date> (manual review): ...'
            --   'GENUINE (manual review). ...'
            '{analysis,claims}',            '<corrected-claims-json-array>'::jsonb),
            '{analysis,score_adjustments}', '<corrected-score-adjustments-json>'::jsonb),
            '{categories}',                 '<corrected-categories-json-array>'::jsonb),
            '{verification_status}',
                to_jsonb('<verified_false|insufficient_evidence|verified_true|uncertain>'::text)),
            '{overall}',                    to_jsonb(<corrected-overall-int>)),

    -- The array column. Keep in step with confidence_scores.categories above.
    -- Spanish labels included; repair accents.
    disinformation_categories = '<corrected-categories-array>',

    -- Bilingual prose. Repair mojibake here too (Nicol\b00e1s -> Nicolás) and
    -- re-attribute anything that is the host's phrasing, not our finding.
    explanation = jsonb_build_object(
        'english', '<corrected-english-explanation>',
        'spanish', '<corrected-spanish-explanation>'
    ),

-- ---------------------------------------------------------------------------
-- 4. PROVENANCE. Never leave a hand edit wearing a model's name.
-- ---------------------------------------------------------------------------
    reviewed_by = 'manual-consistency-pass-<YYYY-MM-DD>',
    reviewed_at = now(),
    updated_at  = now()
where s.id = :'snippet_id'::uuid;

-- ---------------------------------------------------------------------------
-- 5. UNHIDE. Scoped to this one snippet -- never a set-based delete.
--    One row here hides the clip from EVERY non-admin viewer, including via
--    its direct URL, because get_snippet/get_public_snippet do not scope the
--    EXISTS check to the caller.
-- ---------------------------------------------------------------------------
delete from user_hide_snippets where snippet = :'snippet_id'::uuid;

-- ---------------------------------------------------------------------------
-- 6. CLOSE THE QUEUE ROW. Note the column is snippet_id here, but `snippet`
--    in user_hide_snippets and snippet_analysis_snapshot. They differ.
-- ---------------------------------------------------------------------------
update downvote_review_queue
set status = 'completed', processed_at = now()
where snippet_id = :'snippet_id'::uuid;

-- ---------------------------------------------------------------------------
-- 7. RECORD THE VERDICT so the reason survives the session.
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
--         reviewed_by must be your marker; queue_status 'completed';
--         the two category fields must agree.
-- ---------------------------------------------------------------------------
select (select count(*) from user_hide_snippets where snippet = :'snippet_id'::uuid) as hide_rows,
       (select status from downvote_review_queue where snippet_id = :'snippet_id'::uuid) as queue_status,
       (confidence_scores->>'overall')::int        as overall,
       confidence_scores->>'verification_status'   as verification_status,
       jsonb_array_length(confidence_scores->'categories') as n_cs_categories,
       array_length(disinformation_categories,1)   as n_array_categories,
       reviewed_by,
       to_char(reviewed_at,'YYYY-MM-DD HH24:MI')   as reviewed_at,
       explanation::text ~ '\\b00[0-9a-f]{2}'      as still_has_mojibake
from snippets
where id = :'snippet_id'::uuid;

-- Then open https://verdad.app/snippet/<snippet-uuid> and confirm it renders.

-- ---------------------------------------------------------------------------
-- ROLLBACK, if the correction turns out wrong.
--
-- This restores VISIBILITY as well as the analysis. Restoring the analysis
-- alone would leave the rejected analysis publicly readable, because the hide
-- row is what kept it out of get_snippet and get_public_snippet.
--
-- Safe because the guard above asserted the snippet was hidden before the
-- correction, so re-inserting one NULL-user hide row returns it to its prior
-- state. user_hide_snippets has a unique constraint on `snippet` (the triggers
-- rely on ON CONFLICT (snippet)), so the insert is idempotent.
-- ---------------------------------------------------------------------------
-- \set snippet_id '<snippet-uuid>'
-- \set batch      'manual-<YYYY-MM-DD>-<short-uuid>'
--
-- begin;
--
-- -- a. analysis
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
--
-- -- b. visibility: re-hide, matching what the triggers write (NULL user)
-- insert into user_hide_snippets (snippet)
-- values (:'snippet_id'::uuid)
-- on conflict (snippet) do nothing;
--
-- -- c. reopen the review queue row
-- update downvote_review_queue
-- set status = 'pending', processed_at = null
-- where snippet_id = :'snippet_id'::uuid;
--
-- -- d. record that the restoration was reversed
-- insert into snippet_hide_review (snippet, batch, verdict, why, reviewed_at)
-- values (
--     :'snippet_id'::uuid,
--     :'batch',
--     'reverted',
--     '<why the correction was wrong; snippet re-hidden and queue reopened>',
--     now()
-- );
--
-- commit;
--
-- -- verify the revert: hide_rows must be 1 and queue_status 'pending'
-- -- select (select count(*) from user_hide_snippets where snippet = :'snippet_id'::uuid) as hide_rows,
-- --        (select status from downvote_review_queue where snippet_id = :'snippet_id'::uuid) as queue_status;
