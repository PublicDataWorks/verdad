-- VER-452: a killed Stage 1 poller run leaves its audio file in Processing (the reset hook covers only by-id runs).
-- Rows stuck over 2 h go back to New, except those with a Stage 1 response (a rerun would duplicate it) and those
-- stuck over 7 days, whose requeue is a backlog decision. A file that keeps killing its run ends in Error.

CREATE OR REPLACE FUNCTION public.sweep_stuck_audio_files(p_max_attempts integer DEFAULT 3)
 RETURNS jsonb
 LANGUAGE plpgsql
 SET search_path = ''
AS $function$
DECLARE
    requeued integer;
    errored integer;
BEGIN
    UPDATE public.audio_files a
    SET status = 'Error', error_message = 'Stage 1 run died ' || p_max_attempts || ' times in Processing'
    WHERE a.status = 'Processing'
      AND a.updated_at < now() - interval '2 hours'
      AND a.updated_at > now() - interval '7 days'
      AND a.retry_attempts >= p_max_attempts
      AND NOT EXISTS (SELECT 1 FROM public.stage_1_llm_responses r WHERE r.audio_file = a.id);
    GET DIAGNOSTICS errored = ROW_COUNT;

    UPDATE public.audio_files a
    SET status = 'New', retry_attempts = a.retry_attempts + 1
    WHERE a.status = 'Processing'
      AND a.updated_at < now() - interval '2 hours'
      AND a.updated_at > now() - interval '7 days'
      AND a.retry_attempts < p_max_attempts
      AND NOT EXISTS (SELECT 1 FROM public.stage_1_llm_responses r WHERE r.audio_file = a.id);
    GET DIAGNOSTICS requeued = ROW_COUNT;

    RETURN jsonb_build_object('requeued', requeued, 'errored', errored);
END;
$function$;

COMMENT ON COLUMN public.audio_files.retry_attempts IS
    'Times sweep_retryable_audio_errors() (VER-417) or sweep_stuck_audio_files() (VER-452) has re-queued this file.';

-- Not an RPC: only the cron job (runs as postgres) and service_role may call it.
REVOKE EXECUTE ON FUNCTION public.sweep_stuck_audio_files(integer) FROM public, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.sweep_stuck_audio_files(integer) TO service_role;

-- pg_cron is absent on a local reset; skip the job there.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_cron') THEN
        PERFORM cron.schedule('sweep_stuck_audio_files', '35 * * * *', 'SELECT public.sweep_stuck_audio_files()');
    END IF;
END $$;
