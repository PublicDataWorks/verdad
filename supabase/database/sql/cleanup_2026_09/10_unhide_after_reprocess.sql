-- cleanup_2026_09 / step 10: un-hide ONE BATCH of reprocessed snippets that pass the feed threshold (WRITES).
--
-- Context (2026-09-15): the snippet quarantine was NOT executed as a status
-- change (01/04/05/09 are superseded). Instead every selected snippet got a row
-- in public.user_hide_snippets with "user" IS NULL, and snippet_quarantine_log
-- (02's DDL, verbatim) is the audit table: one row per (snippet, batch) with
-- previous_status = 'Processed', reason, quarantined_at, restored_at NULL.
-- snippets.status was left untouched, so a hidden snippet is still
-- 'Processed' with its old 95+ score until it is re-queued and re-analysed.
--
-- Run AFTER the batch has been re-queued (src/scripts/reprocess_snippets.py
-- --quarantine-batch <batch> --stage 3 --execute) and Stage 3/4 have finished
-- with it. For every log row of the chosen batch that is still open
-- (restored_at IS NULL) whose snippet
--   * has been re-analysed since it was hidden  (see "reprocessed" below), and
--   * now carries a real verdict above the feed threshold
--     (status = 'Processed' AND (confidence_scores->>'overall')::int >= 95)
-- this deletes the NULL-user user_hide_snippets row and stamps restored_at.
--
-- Snippets that were re-analysed and now score below 95 are left alone on
-- purpose: their log row stays open and their hide row stays in place. The
-- feed filter (get_snippets: overall >= 95) already excludes them, so the hide
-- is redundant but harmless, and keeping the log row open records that the
-- cleanup's verdict on them stood. The same goes for snippets that ended in
-- 'Error' or are still 'New'/'Processing'/'Ready for review'/'Reviewing'.
--
-- "Reprocessed" = the live analysis differs from the 04b snapshot for the
-- batch AND snippets.updated_at is later than the log row's quarantined_at.
-- Without the snapshot check a snippet that was never re-queued would qualify
-- immediately (it is still 'Processed' at 95+), so 04b MUST have a snapshot
-- for every log row of the batch before this runs (guard query in README.md);
-- a snippet with no snapshot row is never un-hidden by this file.
--
-- Rows in user_hide_snippets with a non-NULL "user" are never touched: those are
-- individual users' own hides. The ~200 pre-existing NULL-user rows written by
-- the 2-dislike trigger are not in snippet_quarantine_log, so the join keeps
-- them out as well.
--
-- Idempotent: a snippet whose log row is already stamped is skipped, and the
-- DELETE matches nothing on a second run. Chunks of 5,000 log rows per run so it
-- stays under statement_timeout; repeat until the final UPDATE reports 0 rows.
-- If the Management API gateway returns HTTP 502 after ~30 s, the statement is
-- still running and commits on its own; verify with the queries at the end
-- rather than re-sending immediately.

BEGIN;

WITH params AS (
    SELECT 'hide-2026-09-15-heuristics'::text AS batch,   -- <- edit: -heuristics, -embeddings or -noevidence-premarch
           5000                               AS chunk_size
),
todo AS (
    SELECT l.id AS log_id, l.snippet
    FROM public.snippet_quarantine_log l
    JOIN public.snippets s ON s.id = l.snippet
    JOIN public.snippet_analysis_snapshot x ON x.snippet = l.snippet AND x.batch = l.batch
    CROSS JOIN params p
    WHERE l.batch = p.batch
      AND l.restored_at IS NULL
      AND s.status = 'Processed'
      AND (s.confidence_scores->>'overall')::int >= 95
      AND s.updated_at > l.quarantined_at
      AND (s.explanation, s.confidence_scores, s.stage_3_prompt_version_id)
          IS DISTINCT FROM (x.explanation, x.confidence_scores, x.stage_3_prompt_version_id)
    ORDER BY l.quarantined_at
    LIMIT (SELECT chunk_size FROM params)
),
unhidden AS (
    DELETE FROM public.user_hide_snippets h
    USING  todo t
    WHERE  h.snippet = t.snippet
      AND  h."user" IS NULL
    RETURNING h.snippet
)
UPDATE public.snippet_quarantine_log l
SET    restored_at = now()
FROM   todo t
WHERE  l.id = t.log_id
  AND  l.restored_at IS NULL;

COMMIT;

-- Verify (read-only):
-- SELECT batch, reason,
--        count(*) FILTER (WHERE restored_at IS NULL)     AS still_hidden,
--        count(*) FILTER (WHERE restored_at IS NOT NULL) AS unhidden
-- FROM public.snippet_quarantine_log GROUP BY batch, reason ORDER BY 1, 2;
--
-- -- Open log rows whose snippet was re-analysed but stays hidden, by outcome:
-- SELECT s.status,
--        (s.confidence_scores->>'overall')::int >= 95 AS above_95,
--        count(*)
-- FROM public.snippet_quarantine_log l
-- JOIN public.snippets s ON s.id = l.snippet
-- WHERE l.batch = 'hide-2026-09-15-heuristics' AND l.restored_at IS NULL
--   AND s.updated_at > l.quarantined_at
-- GROUP BY 1, 2 ORDER BY 1, 2;
--
-- -- Hide rows and log rows must agree: every open log row still has its NULL-user hide row
-- SELECT count(*) AS open_log_rows_without_hide
-- FROM public.snippet_quarantine_log l
-- WHERE l.restored_at IS NULL
--   AND NOT EXISTS (SELECT 1 FROM public.user_hide_snippets h WHERE h.snippet = l.snippet AND h."user" IS NULL);
