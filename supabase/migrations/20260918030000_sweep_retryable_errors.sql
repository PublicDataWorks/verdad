-- Bounded automatic retry for snippets parked in Error (VER-382; the drain itself is VER-379).
--
-- Why. `Error` is a terminal state: public.fetch_a_new_snippet_and_reserve_it() only ever selects
-- status = 'New', stage_3/flows.py carries a "TODO: Retry failed snippets (status: Error)" that was
-- never written, and stage_3/tasks.py sends every exception to the same state with no attempt
-- counter. Because transcription and translation are Stage 3 outputs, a row that fails Stage 3 has
-- no text at all and is invisible to search. On 2026-09-18 that pile was 275,826 rows, about
-- 204,000 of them in a retryable class, three of those classes still growing:
--
--   KeyError 'search'/'run'/'call' (VER-363 bug, fixed 2026-09-02)  100,193   57 with text
--   skipped_backlog_pre_2026-09-02  (deliberate park, NOT swept)      58,837
--   Gemini 503 UNAVAILABLE                                             44,543   still growing
--   Gemini 429 RESOURCE_EXHAUSTED                                      27,244   still growing
--   No response from Gemini                                            18,055   still growing
--   other (validation, cut-off, 404 model, MCP session, 500s)          14,218
--   Intentionally Hidden            (deliberate, NOT swept)            12,736
--
-- Design. Do not widen the hot-path reservation RPC that five Stage 3 loops hammer. Instead, the
-- same shape as sweep_stuck_snippets (20260917080000, VER-371): a function that moves a bounded
-- batch of retryable rows back into the queue, run from pg_cron, with a counter so nothing loops
-- forever. The counter is incremented BY THE SWEEPER when it re-queues a row, so this needs no
-- pipeline code change and no deploy: the original attempt is implicit, and p_max_attempts is the
-- number of sweeps a row may receive.
--
-- Routing. A message that starts with '[Stage 4]' means Stage 3 completed and the review failed;
-- those rows already have text and go back to 'Ready for review', not 'New', so Stage 3 is not
-- re-run for nothing. Everything else goes to 'New'.
--
-- What counts as retryable: the fixed VER-363 KeyError class; Gemini 503 / 429 / 500 / "temporarily
-- unavailable" / "No response from Gemini"; Stage 4 MCP session failures. What does not: the two
-- deliberate parks above; 404 "model not found" (a config problem, re-running reproduces it);
-- validation and "response was cut off" errors (deterministic on that clip under the current prompt).
-- Widen the pattern list deliberately, not by accident.
--
-- Ordering. ORDER BY recorded_at DESC, matching Stage 3's newest-first poll, so recent failures come
-- back first. Measured 2026-09-18: the selection runs in 5 ms via idx_snippets_recorded_at, so no
-- new index is needed.
--
-- THE CRON JOB IS NOT SCHEDULED HERE ON PURPOSE. p_batch is the quota dial: 200 rows every ten
-- minutes is a ceiling of 28,800/day, while Stage 3 actually completes about 2,800/day, so the real
-- rate is bounded by the worker and the sweeper simply keeps 'New' topped up. How many days of
-- Gemini quota the backlog is worth is a product decision (VER-379). When it is made:
--
--   SELECT cron.schedule('sweep_retryable_errors', '*/10 * * * *',
--                        $$SELECT public.sweep_retryable_errors(200)$$);
--
-- and to pause: SELECT cron.unschedule('sweep_retryable_errors');
-- Do it after PR #98's evidence-gate hardening is deployed, so re-analysis runs under the new gate.
--
-- Manual use:  SELECT public.sweep_retryable_errors(50);   -- returns counts by destination
--
-- Rollback:  DROP FUNCTION public.sweep_retryable_errors(integer, integer);
--            ALTER TABLE public.snippets DROP COLUMN analysis_attempts;
--
-- Lock note: ADD COLUMN with a constant default is metadata-only on Postgres 11+ (no rewrite), but it
-- still takes ACCESS EXCLUSIVE for an instant. Apply with a short lock_timeout so it fails fast
-- instead of queuing behind a long reader and blocking the pipeline (see VER-378).

SET lock_timeout = '3s';

ALTER TABLE public.snippets
    ADD COLUMN IF NOT EXISTS analysis_attempts smallint NOT NULL DEFAULT 0;

COMMENT ON COLUMN public.snippets.analysis_attempts IS
    'Times sweep_retryable_errors() has re-queued this row after an Error. The original attempt is not counted. VER-382.';

RESET lock_timeout;

CREATE OR REPLACE FUNCTION public.sweep_retryable_errors(
    p_batch integer DEFAULT 200,
    p_max_attempts integer DEFAULT 3
)
 RETURNS jsonb
 LANGUAGE plpgsql
 SET search_path = ''
AS $function$
DECLARE
    to_stage3 integer;
    to_stage4 integer;
BEGIN
    WITH picked AS (
        SELECT id, error_message
        FROM public.snippets
        WHERE status = 'Error'
          AND analysis_attempts < p_max_attempts
          AND error_message IS NOT NULL
          AND error_message NOT LIKE 'skipped_backlog%'
          AND error_message <> 'Intentionally Hidden'
          AND (
                error_message LIKE 'KeyError%'
             OR error_message LIKE '%503%'
             OR error_message LIKE '%UNAVAILABLE%'
             OR error_message LIKE '%429%'
             OR error_message LIKE '%RESOURCE_EXHAUSTED%'
             OR error_message LIKE '%No response from Gemini%'
             OR error_message LIKE '%500 Internal error%'
             OR error_message LIKE '%temporarily unavailable%'
             OR error_message LIKE '%Failed to create MCP session%'
          )
        ORDER BY recorded_at DESC
        LIMIT p_batch
        FOR UPDATE SKIP LOCKED
    ),
    moved AS (
        UPDATE public.snippets s
        SET status = CASE WHEN p.error_message LIKE '[Stage 4]%'
                          THEN 'Ready for review'::public.processing_status
                          ELSE 'New'::public.processing_status END,
            error_message = NULL,
            analysis_attempts = s.analysis_attempts + 1
        FROM picked p
        WHERE s.id = p.id
        RETURNING s.status
    )
    SELECT count(*) FILTER (WHERE status = 'New'),
           count(*) FILTER (WHERE status = 'Ready for review')
    INTO to_stage3, to_stage4
    FROM moved;

    RETURN jsonb_build_object('requeued_stage3', to_stage3, 'requeued_stage4', to_stage4);
END;
$function$;

COMMENT ON FUNCTION public.sweep_retryable_errors(integer, integer) IS
    'Move up to p_batch retryable Error snippets back to New (or Ready for review for [Stage 4] failures), at most p_max_attempts times each. Not scheduled by default; see the migration header. VER-382.';

REVOKE EXECUTE ON FUNCTION public.sweep_retryable_errors(integer, integer) FROM public, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.sweep_retryable_errors(integer, integer) TO service_role;
