-- VER-417 follow-up: 'NoneType' replies are mostly deterministic per file. 4 h read (1 Oct): 5 of 15 recovered, all
-- on the first retry; later attempts 0 of 6. Retry them once. Rollback: re-apply the function from 20261001100000.

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
             OR (a.error_message = '''NoneType'' object is not subscriptable' AND a.retry_attempts = 0)
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
    'Move up to p_batch audio files with a transient Stage 1 error (last 7 days, failed over an hour ago, no Stage 1 response) back to New, at most p_max_attempts times each (''NoneType'' replies once). VER-417.';
