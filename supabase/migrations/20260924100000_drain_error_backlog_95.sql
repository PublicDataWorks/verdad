-- VER-389: 95+ Error rows go back to New so Stage 3 rebuilds the evidence (sweep_retryable_errors would send
-- '[Stage 4]' failures to Stage 4 on stale evidence). A row already in snippet_requeue_log is never picked.
-- Scheduled from cleanup_2026_09/16_drain_error_backlog_95.sql.
-- Rollback: DROP FUNCTION public.drain_error_backlog_95(integer);  (the log table predates this migration)

-- Hand-created in production by cleanup_2026_09/15 step 0; repeated here so a fresh database has it.
CREATE TABLE IF NOT EXISTS public.snippet_requeue_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    snippet         UUID NOT NULL,
    previous_status public.processing_status NOT NULL,
    previous_error  TEXT,
    new_status      public.processing_status NOT NULL,
    batch           TEXT NOT NULL,
    requeued_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (snippet, batch)
);
CREATE INDEX IF NOT EXISTS idx_snippet_requeue_log_batch ON public.snippet_requeue_log (batch);
ALTER TABLE public.snippet_requeue_log ENABLE ROW LEVEL SECURITY;
GRANT ALL ON TABLE public.snippet_requeue_log TO service_role;

CREATE OR REPLACE FUNCTION public.drain_error_backlog_95(p_batch integer DEFAULT 50)
 RETURNS jsonb
 LANGUAGE plpgsql
 STRICT
 SET search_path = ''
AS $function$
DECLARE
    v_batch text := 'drain-95-' || to_char(now() AT TIME ZONE 'utc', 'YYYY-MM-DD');
    v_requeued integer;
BEGIN
    WITH picked AS (
        SELECT s.id, s.status, s.error_message
        FROM public.snippets s
        WHERE s.status = 'Error'
          AND s.recorded_at >= '2026-08-01 00:00+00'
          AND (s.confidence_scores->>'overall')::integer >= 95
          AND s.analysis_attempts < 3
          AND coalesce(s.error_message, '') NOT LIKE 'skipped_backlog%'
          AND coalesce(s.error_message, '') <> 'Intentionally Hidden'
          AND NOT EXISTS (SELECT 1 FROM public.snippet_requeue_log l WHERE l.snippet = s.id)
        ORDER BY s.recorded_at DESC
        LIMIT p_batch
        FOR UPDATE OF s SKIP LOCKED
    ),
    moved AS (
        UPDATE public.snippets s
        SET status = 'New'::public.processing_status,
            error_message = NULL,
            analysis_attempts = s.analysis_attempts + 1
        FROM picked p
        WHERE s.id = p.id
        RETURNING s.id, p.status AS previous_status, p.error_message AS previous_error
    )
    INSERT INTO public.snippet_requeue_log (snippet, previous_status, previous_error, new_status, batch)
    SELECT id, previous_status, previous_error, 'New'::public.processing_status, v_batch
    FROM moved;

    GET DIAGNOSTICS v_requeued = ROW_COUNT;

    RETURN jsonb_build_object('batch', v_batch, 'requeued', v_requeued);
END;
$function$;

COMMENT ON FUNCTION public.drain_error_backlog_95(integer) IS
    'Move up to p_batch Error snippets scoring 95+ (recorded since 2026-08-01) back to New for a Stage 3 rebuild, logged in snippet_requeue_log as drain-95-<utc day>. Not scheduled by default. VER-389.';

REVOKE EXECUTE ON FUNCTION public.drain_error_backlog_95(integer) FROM public, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.drain_error_backlog_95(integer) TO service_role;
