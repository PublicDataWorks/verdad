-- Correct a VERDAD snippet's analysis and restore it to verdad.app.
--
-- HOW TO RUN
--   1. Copy this file into the scratchpad, never edit it in place.
--   2. Replace the two literals in step 0 and every <placeholder> below.
--   3. Show the filled file to a human and run it ONLY after they approve.
--      CLAUDE.md requires human confirmation before any UPDATE/DELETE on production.
--   4. Run the verification block at the bottom afterwards.
--
--   This file uses NO psql meta-commands, so it runs unchanged through psql
--   "$SUPABASE_DB_URL" -f <file> or through the Supabase MCP execute_sql tool.
--   Send it as ONE unit either way: the settings in step 0 are transaction-local
--   (is_local => true), so running it statement by statement loses them and the
--   atomicity this whole template exists for.
--
-- PRECONDITION asserted in step 2:
--   the snippet currently has at least one user_hide_snippets row.
-- The rollback relies on that assertion to restore visibility correctly. If the
-- snippet is NOT hidden you are not doing an unhide; stop and re-read SKILL.md.
--
-- ORDER: settings -> snapshot -> assert -> rewrite -> provenance -> unhide ->
--        clear quarantine -> close queue -> drop embedding -> record verdict.

begin;

-- ---------------------------------------------------------------------------
-- 0. The only two values to fill in. Everything below reads them back, so the
--    uuid and batch appear exactly once.
-- ---------------------------------------------------------------------------
select set_config('verdad.snippet_id', '<snippet-uuid>',                    true),
       set_config('verdad.batch',      'manual-<YYYY-MM-DD>-<short-uuid>',   true);

-- ---------------------------------------------------------------------------
-- 1. SNAPSHOT (rollback point). Must run before any write.
--
-- `labels` is NOT NULL DEFAULT '[]'::jsonb. An explicit NULL does NOT fall back
-- to the default, it violates the constraint, so the column is omitted and takes
-- its default. Consequence: label associations are NOT captured, so the rollback
-- restores analysis and visibility but not labels. Snapshot those separately if
-- a correction changes them.
--
-- snapshot_at is also what the rollback uses to find the quarantine rows this
-- run restored, so do not backdate it.
-- ---------------------------------------------------------------------------
insert into snippet_analysis_snapshot (
    snippet, batch, snapshot_at, status, title, summary, explanation,
    disinformation_categories, confidence_scores, grounding_metadata,
    thought_summaries, analyzed_by, reviewed_by, reviewed_at,
    stage_3_prompt_version_id
)
select s.id, current_setting('verdad.batch'), now(), s.status, s.title, s.summary,
       s.explanation, s.disinformation_categories, s.confidence_scores,
       s.grounding_metadata, s.thought_summaries, s.analyzed_by, s.reviewed_by,
       s.reviewed_at, s.stage_3_prompt_version_id
from snippets s
where s.id = current_setting('verdad.snippet_id')::uuid;

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
            'snippet % has no hide row; this template is for unhiding. Re-read step 1 of SKILL.md.',
            v_snippet;
    end if;
end
$guard$;

-- ---------------------------------------------------------------------------
-- 3. REWRITE THE ANALYSIS
--
-- Categories live in TWO places and must move together, or the restored snippet
-- carries contradictory verdict data:
--   * disinformation_categories      -- the array column
--   * confidence_scores.categories   -- a jsonb array copy
-- score_adjustments must be refreshed too, or adjustment_reason still describes
-- the old verdict.
--
-- Stage 4 reviewer 1.3.0 rules (live since 2026-09-22, VER-391):
--   * claims[] holds ONLY claims a retrieved source contradicts; each evidence
--     opens with that source.
--   * A searched-but-empty or never-searched claim gets NO claims[] entry. Name
--     it in explanation and in score_adjustments.adjustment_reason.
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
-- NOTE: confidence_scores.analysis.explanation is EMPTY on production rows. The
--       prose lives in the top-level explanation jsonb. Edit that.
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
where s.id = current_setting('verdad.snippet_id')::uuid;

-- ---------------------------------------------------------------------------
-- 5. UNHIDE. Scoped to this one snippet -- never a set-based delete.
--    One row here hides the clip from EVERY non-admin viewer, including via its
--    direct URL, because get_snippet/get_public_snippet do not scope the EXISTS
--    check to the caller.
-- ---------------------------------------------------------------------------
delete from user_hide_snippets
where snippet = current_setting('verdad.snippet_id')::uuid;

-- ---------------------------------------------------------------------------
-- 6. CLEAR THE QUARANTINE LOG, or the correction gets overwritten later.
--
-- Most NULL-user hides came from the 2026-09 cleanup batches, not from a
-- dislike. reprocess_snippets.py --quarantine-batch selects
--   snippet_quarantine_log WHERE batch IN (...) AND restored_at IS NULL
-- (see reprocess_snippets.py and fetch_quarantine_batch_snippet_ids). Deleting
-- the hide row while leaving restored_at NULL therefore leaves the snippet
-- eligible for a later re-run, which re-analyses it and overwrites this
-- hand correction. Stamping restored_at takes it out of that selector.
--
-- Only rows still NULL are touched, so a row some earlier restore already
-- stamped keeps its original timestamp, and the rollback can tell ours apart.
-- ---------------------------------------------------------------------------
update snippet_quarantine_log
set restored_at = now()
where snippet = current_setting('verdad.snippet_id')::uuid
  and restored_at is null;

-- ---------------------------------------------------------------------------
-- 7. CLOSE THE DOWNVOTE QUEUE ROW. Note the column is snippet_id here, but
--    `snippet` in user_hide_snippets, snippet_quarantine_log,
--    snippet_analysis_snapshot and snippet_hide_review. They differ.
-- ---------------------------------------------------------------------------
update downvote_review_queue
set status = 'completed', processed_at = now()
where snippet_id = current_setting('verdad.snippet_id')::uuid;

-- ---------------------------------------------------------------------------
-- 8. DROP THE STALE EMBEDDING so Stage 5 re-embeds the corrected text.
--    The vector was built from the old explanation; leaving it makes the clip
--    retrievable by its withdrawn wording and not by its corrected wording.
--    Equivalent to SupabaseClient.delete_vector_embedding_of_snippet.
-- ---------------------------------------------------------------------------
delete from snippet_embeddings
where snippet = current_setting('verdad.snippet_id')::uuid;

-- ---------------------------------------------------------------------------
-- 9. RECORD THE VERDICT so the reason survives the session.
--    snippet_hide_review is PRIMARY KEY (snippet, batch), so this must upsert:
--    a plain insert collides with itself if the batch is ever reused, and it is
--    what lets the rollback flip the same row to 'reverted'.
-- ---------------------------------------------------------------------------
insert into snippet_hide_review (snippet, batch, verdict, why, reviewed_at)
values (
    current_setting('verdad.snippet_id')::uuid,
    current_setting('verdad.batch'),
    'restored',
    '<why: what was wrong with the analysis, what was corrected, what it now rests on>',
    now()
)
on conflict (snippet, batch) do update
set verdict     = excluded.verdict,
    why         = excluded.why,
    reviewed_at = excluded.reviewed_at;

commit;

-- ---------------------------------------------------------------------------
-- VERIFY. Fill the uuid once more; this block runs on its own.
--   hide_rows 0; overall >= 95 for the feed; reviewed_by your marker;
--   queue_status 'completed'; unrestored_quarantine 0; embedding_rows 0 until
--   Stage 5 runs; the two category counts equal.
-- ---------------------------------------------------------------------------
select (select count(*) from user_hide_snippets where snippet = s.id)        as hide_rows,
       (select count(*) from snippet_quarantine_log q
         where q.snippet = s.id and q.restored_at is null)                   as unrestored_quarantine,
       (select status from downvote_review_queue where snippet_id = s.id)    as queue_status,
       (select count(*) from snippet_embeddings e where e.snippet = s.id)    as embedding_rows,
       (s.confidence_scores->>'overall')::int                                as overall,
       s.confidence_scores->>'verification_status'                           as verification_status,
       jsonb_array_length(s.confidence_scores->'categories')                 as n_cs_categories,
       array_length(s.disinformation_categories,1)                           as n_array_categories,
       s.reviewed_by,
       to_char(s.reviewed_at,'YYYY-MM-DD HH24:MI')                           as reviewed_at,
       s.explanation::text ~ '\\b00[0-9a-f]{2}'                              as still_has_mojibake
from snippets s
where s.id = '<snippet-uuid>'::uuid;

-- Then open https://verdad.app/snippet/<snippet-uuid> and confirm it renders.

-- ---------------------------------------------------------------------------
-- ROLLBACK, if the correction turns out wrong.
--
-- Restores VISIBILITY as well as the analysis. Restoring the analysis alone
-- would leave the rejected analysis publicly readable, because the hide row is
-- what kept it out of get_snippet and get_public_snippet.
--
-- Safe because step 2 asserted the snippet was hidden before the correction, so
-- re-inserting one NULL-user hide row returns it to its prior state.
-- user_hide_snippets is PRIMARY KEY (snippet), so the insert is idempotent.
--
-- Uncomment and fill the same two values as step 0.
-- ---------------------------------------------------------------------------
-- begin;
--
-- select set_config('verdad.snippet_id', '<snippet-uuid>',                  true),
--        set_config('verdad.batch',      'manual-<YYYY-MM-DD>-<short-uuid>', true);
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
-- where p.snippet = current_setting('verdad.snippet_id')::uuid
--   and p.batch   = current_setting('verdad.batch')
--   and s.id      = p.snippet;
--
-- -- b. visibility: re-hide, matching what the triggers write (NULL user)
-- insert into user_hide_snippets (snippet)
-- values (current_setting('verdad.snippet_id')::uuid)
-- on conflict (snippet) do nothing;
--
-- -- c. re-quarantine ONLY the rows this run stamped. Keyed on the snapshot's
-- --    own timestamp, so a row restored before this run keeps its timestamp.
-- update snippet_quarantine_log q
-- set restored_at = null
-- where q.snippet = current_setting('verdad.snippet_id')::uuid
--   and q.restored_at >= (
--         select p.snapshot_at from snippet_analysis_snapshot p
--         where p.snippet = current_setting('verdad.snippet_id')::uuid
--           and p.batch   = current_setting('verdad.batch'));
--
-- -- d. reopen the downvote queue row
-- update downvote_review_queue
-- set status = 'pending', processed_at = null
-- where snippet_id = current_setting('verdad.snippet_id')::uuid;
--
-- -- e. drop the embedding again: it was built from the analysis being withdrawn
-- delete from snippet_embeddings
-- where snippet = current_setting('verdad.snippet_id')::uuid;
--
-- -- f. flip the same verdict row to 'reverted'. A plain insert would violate
-- --    snippet_hide_review's PRIMARY KEY (snippet, batch) and abort the whole
-- --    rollback, since the forward run already wrote this (snippet, batch).
-- insert into snippet_hide_review (snippet, batch, verdict, why, reviewed_at)
-- values (
--     current_setting('verdad.snippet_id')::uuid,
--     current_setting('verdad.batch'),
--     'reverted',
--     '<why the correction was wrong; snippet re-hidden, quarantine and queue reopened>',
--     now()
-- )
-- on conflict (snippet, batch) do update
-- set verdict     = excluded.verdict,
--     why         = excluded.why,
--     reviewed_at = excluded.reviewed_at;
--
-- commit;
--
-- -- verify the revert: hide_rows 1, queue_status 'pending', verdict 'reverted'
-- -- select (select count(*) from user_hide_snippets where snippet = '<snippet-uuid>'::uuid) as hide_rows,
-- --        (select status from downvote_review_queue where snippet_id = '<snippet-uuid>'::uuid) as queue_status,
-- --        (select verdict from snippet_hide_review where snippet = '<snippet-uuid>'::uuid
-- --           and batch = 'manual-<YYYY-MM-DD>-<short-uuid>') as verdict;
