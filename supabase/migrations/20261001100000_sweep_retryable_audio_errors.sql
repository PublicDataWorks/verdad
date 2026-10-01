-- VER-417: Stage 1 never retries an audio file in Error (stage_1/flows.py TODO), so each transient Gemini failure
-- is a recording never analysed. Re-queue recent transient failures, at most p_max_attempts times, an hour apart.
-- *** Apply the ADD COLUMN as one request: BEGIN; SET LOCAL lock_timeout = '3s'; ALTER ...; COMMENT ...; COMMIT;
-- Rollback: cron.unschedule('sweep_retryable_audio_errors'); DROP FUNCTION; DROP COLUMN (re-queued rows stay New).

SET lock_timeout = '3s';

ALTER TABLE public.audio_files
    ADD COLUMN IF NOT EXISTS retry_attempts smallint NOT NULL DEFAULT 0;

COMMENT ON COLUMN public.audio_files.retry_attempts IS
    'Times sweep_retryable_audio_errors() has re-queued this file after an Error. VER-417.';

RESET lock_timeout;

CREATE OR REPLACE FUNCTION public.sweep_retryable_audio_errors(
    p_batch integer DEFAULT 20,
    p_max_attempts integer DEFAULT 3
)
 RETURNS jsonb
 LANGUAGE plpgsql
 SET search_path = ''
AS $function$
DECLARE
    requeued integer;
BEGIN
    WITH picked AS (
        SELECT a.id
        FROM public.audio_files a
        WHERE a.status = 'Error'
          AND a.recorded_at > now() - interval '7 days'
          AND a.updated_at < now() - interval '1 hour'
          AND a.retry_attempts < p_max_attempts
          AND (
                a.error_message LIKE '503 %'
             OR a.error_message LIKE '429 %'
             OR a.error_message LIKE 'No response from Gemini%'
             OR a.error_message = '''NoneType'' object is not subscriptable'
             OR a.error_message LIKE '%canceling statement due to statement timeout%'
          )
          AND NOT EXISTS (SELECT 1 FROM public.stage_1_llm_responses r WHERE r.audio_file = a.id)
        ORDER BY a.recorded_at DESC
        LIMIT p_batch
        FOR UPDATE SKIP LOCKED
    )
    UPDATE public.audio_files a
    SET status = 'New'::public.processing_status,
        error_message = NULL,
        retry_attempts = a.retry_attempts + 1
    FROM picked p
    WHERE a.id = p.id;

    GET DIAGNOSTICS requeued = ROW_COUNT;
    RETURN jsonb_build_object('requeued', requeued);
END;
$function$;

COMMENT ON FUNCTION public.sweep_retryable_audio_errors(integer, integer) IS
    'Move up to p_batch audio files with a transient Stage 1 error (last 7 days, failed over an hour ago, no Stage 1 response) back to New, at most p_max_attempts times each. VER-417.';

REVOKE EXECUTE ON FUNCTION public.sweep_retryable_audio_errors(integer, integer) FROM public, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.sweep_retryable_audio_errors(integer, integer) TO service_role;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_cron') THEN
        PERFORM cron.schedule('sweep_retryable_audio_errors', '25,55 * * * *',
            'SELECT public.sweep_retryable_audio_errors(20)');
    END IF;
END $$;
