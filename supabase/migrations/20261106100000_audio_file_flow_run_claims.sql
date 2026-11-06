-- VER-461: the Stage 1 cancel/crash hook can run after the run's process is gone, so the reserve RPC records the
-- claiming flow run and release_flow_run_audio_files frees that run's Processing files (Processed with a Stage 1
-- response, else New; a crash counts toward retry_attempts like sweep_stuck_audio_files).
-- Apply in one request (one transaction) before deploying the code that passes p_flow_run_id.
-- Rollback: DROP both functions, then restore the zero-argument reserve from the baseline (both copies).

SET lock_timeout = '3s';

ALTER TABLE public.audio_files ADD COLUMN IF NOT EXISTS claimed_by_flow_run uuid;
COMMENT ON COLUMN public.audio_files.claimed_by_flow_run IS
    'Prefect flow run that last reserved this file for Stage 1 (VER-461); NULL for files claimed before it.';

DROP FUNCTION IF EXISTS public.fetch_a_new_audio_file_and_reserve_it();

CREATE OR REPLACE FUNCTION public.fetch_a_new_audio_file_and_reserve_it(p_flow_run_id uuid DEFAULT NULL)
 RETURNS jsonb
 LANGUAGE plpgsql
AS $function$
DECLARE
    audio_file_record jsonb;
BEGIN
    UPDATE public.audio_files
    SET status = 'Processing', claimed_by_flow_run = p_flow_run_id
    WHERE id = (
        SELECT id
        FROM public.audio_files
        WHERE status = 'New'
        ORDER BY recorded_at DESC
        LIMIT 1
        FOR UPDATE SKIP LOCKED
    )
    RETURNING row_to_json(public.audio_files.*) INTO audio_file_record;

    RETURN audio_file_record;
END;
$function$;

GRANT EXECUTE ON FUNCTION public.fetch_a_new_audio_file_and_reserve_it(uuid) TO anon;
GRANT EXECUTE ON FUNCTION public.fetch_a_new_audio_file_and_reserve_it(uuid) TO authenticated;
GRANT EXECUTE ON FUNCTION public.fetch_a_new_audio_file_and_reserve_it(uuid) TO service_role;

CREATE OR REPLACE FUNCTION public.release_flow_run_audio_files(
    p_flow_run_id uuid,
    p_count_attempt boolean DEFAULT false,
    p_max_attempts integer DEFAULT 3
)
 RETURNS jsonb
 LANGUAGE plpgsql
 SET search_path = ''
AS $function$
DECLARE
    processed integer;
    errored integer;
    requeued integer;
BEGIN
    UPDATE public.audio_files a
    SET status = 'Processed'
    WHERE a.claimed_by_flow_run = p_flow_run_id
      AND a.status = 'Processing'
      AND EXISTS (SELECT 1 FROM public.stage_1_llm_responses r WHERE r.audio_file = a.id);
    GET DIAGNOSTICS processed = ROW_COUNT;

    UPDATE public.audio_files a
    SET status = 'Error', error_message = 'Stage 1 run died ' || p_max_attempts || ' times in Processing'
    WHERE a.claimed_by_flow_run = p_flow_run_id
      AND a.status = 'Processing'
      AND p_count_attempt
      AND a.retry_attempts >= p_max_attempts;
    GET DIAGNOSTICS errored = ROW_COUNT;

    UPDATE public.audio_files a
    SET status = 'New', retry_attempts = a.retry_attempts + p_count_attempt::integer
    WHERE a.claimed_by_flow_run = p_flow_run_id
      AND a.status = 'Processing';
    GET DIAGNOSTICS requeued = ROW_COUNT;

    RETURN jsonb_build_object('processed', processed, 'requeued', requeued, 'errored', errored);
END;
$function$;

-- Not an RPC for clients: only the Stage 1 hook (service_role) calls it.
REVOKE EXECUTE ON FUNCTION public.release_flow_run_audio_files(uuid, boolean, integer) FROM public, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.release_flow_run_audio_files(uuid, boolean, integer) TO service_role;
