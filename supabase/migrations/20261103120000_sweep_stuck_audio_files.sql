-- VER-452: a killed Stage 1 poller run leaves its audio file in Processing (the reset hook covers only by-id runs).
-- Rows stuck over 2 h go back to New, except those with a Stage 1 response (a rerun would duplicate it) and those
-- stuck over 7 days, whose requeue is a backlog decision.

CREATE OR REPLACE FUNCTION public.sweep_stuck_audio_files()
 RETURNS jsonb
 LANGUAGE plpgsql
 SET search_path = ''
AS $function$
DECLARE
    requeued integer;
BEGIN
    UPDATE public.audio_files a SET status = 'New'::public.processing_status
    WHERE a.status = 'Processing'
      AND a.updated_at < now() - interval '2 hours'
      AND a.updated_at > now() - interval '7 days'
      AND NOT EXISTS (SELECT 1 FROM public.stage_1_llm_responses r WHERE r.audio_file = a.id);
    GET DIAGNOSTICS requeued = ROW_COUNT;

    RETURN jsonb_build_object('requeued', requeued);
END;
$function$;

-- Not an RPC: only the cron job (runs as postgres) and service_role may call it.
REVOKE EXECUTE ON FUNCTION public.sweep_stuck_audio_files() FROM public, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.sweep_stuck_audio_files() TO service_role;

-- pg_cron is absent on a local reset; skip the job there.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_cron') THEN
        PERFORM cron.schedule('sweep_stuck_audio_files', '35 * * * *', 'SELECT public.sweep_stuck_audio_files()');
    END IF;
END $$;
