-- VER-479: the Stage 3 cancel/crash hook can run after the run's process is gone, so the reserve RPC records the
-- claiming flow run and release_flow_run_snippets frees that run's Processing clips.
-- Apply in one request (one transaction) before deploying the code that passes p_flow_run_id.
-- Rollback: DROP both functions, restore the zero-argument reserve from 20261104100000 (both copies).

SET lock_timeout = '3s';

ALTER TABLE public.snippets ADD COLUMN IF NOT EXISTS claimed_by_flow_run uuid;
COMMENT ON COLUMN public.snippets.claimed_by_flow_run IS
    'Prefect flow run that last reserved this snippet for Stage 3 (VER-479); NULL for snippets claimed before it.';

DROP FUNCTION IF EXISTS public.fetch_a_new_snippet_and_reserve_it();

CREATE OR REPLACE FUNCTION public.fetch_a_new_snippet_and_reserve_it(p_flow_run_id uuid DEFAULT NULL)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY INVOKER
AS $function$
DECLARE
    snippet_record jsonb;
BEGIN
    UPDATE public.snippets
    SET status = 'Processing', claimed_by_flow_run = p_flow_run_id
    WHERE id = (
        SELECT id
        FROM public.snippets
        WHERE status = 'New'
        ORDER BY priority DESC, recorded_at DESC
        LIMIT 1
        FOR UPDATE SKIP LOCKED
    )
    RETURNING (
        row_to_json(public.snippets.*)::jsonb - 'audio_file'::text - 'stage_1_llm_response'::text
    ) || jsonb_build_object(
        'audio_file', (
            SELECT jsonb_build_object(
                'radio_station_name', af.radio_station_name,
                'radio_station_code', af.radio_station_code,
                'location_state', af.location_state,
                'location_city', af.location_city,
                'recorded_at', af.recorded_at,
                'recording_day_of_week', af.recording_day_of_week
            )
            FROM public.audio_files af
            WHERE af.id = public.snippets.audio_file
        ),
        'stage_1_llm_response', (
            SELECT jsonb_build_object(
                'detection_result', s1lr.detection_result
            )
            FROM public.stage_1_llm_responses s1lr
            WHERE s1lr.id = public.snippets.stage_1_llm_response
        )
    ) INTO snippet_record;

    RETURN snippet_record;
END;
$function$;

GRANT EXECUTE ON FUNCTION public.fetch_a_new_snippet_and_reserve_it(uuid) TO anon;
GRANT EXECUTE ON FUNCTION public.fetch_a_new_snippet_and_reserve_it(uuid) TO authenticated;
GRANT EXECUTE ON FUNCTION public.fetch_a_new_snippet_and_reserve_it(uuid) TO service_role;

CREATE OR REPLACE FUNCTION public.release_flow_run_snippets(
    p_flow_run_id uuid,
    p_count_attempt boolean DEFAULT false,
    p_max_attempts integer DEFAULT 3
)
 RETURNS jsonb
 LANGUAGE plpgsql
 SET search_path = ''
AS $function$
DECLARE
    errored integer;
    requeued integer;
BEGIN
    UPDATE public.snippets s
    SET status = 'Error', error_message = 'Stage 3 run died in Processing after ' || p_max_attempts || ' retries'
    WHERE s.claimed_by_flow_run = p_flow_run_id
      AND s.status = 'Processing'
      AND p_count_attempt
      AND s.analysis_attempts >= p_max_attempts;
    GET DIAGNOSTICS errored = ROW_COUNT;

    UPDATE public.snippets s
    SET status = 'New', analysis_attempts = s.analysis_attempts + p_count_attempt::integer
    WHERE s.claimed_by_flow_run = p_flow_run_id
      AND s.status = 'Processing';
    GET DIAGNOSTICS requeued = ROW_COUNT;

    RETURN jsonb_build_object('requeued', requeued, 'errored', errored);
END;
$function$;

-- Not an RPC for clients: only the Stage 3 hook (service_role) calls it.
REVOKE EXECUTE ON FUNCTION public.release_flow_run_snippets(uuid, boolean, integer) FROM public, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.release_flow_run_snippets(uuid, boolean, integer) TO service_role;
