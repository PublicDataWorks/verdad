-- VER-371: killed flow runs (6-hourly restart, OOM, prefect restart) leave their reserved snippet in
-- Processing/Reviewing forever. Live reservations are minutes old (updated_at is trigger-maintained),
-- so anything older than 2 h is dead and goes back to its queue. pg_cron runs this hourly.

CREATE OR REPLACE FUNCTION public.sweep_stuck_snippets()
 RETURNS jsonb
 LANGUAGE plpgsql
 SET search_path = ''
AS $function$
DECLARE
    requeued integer;
    rereview integer;
BEGIN
    UPDATE public.snippets SET status = 'New'
    WHERE status = 'Processing' AND updated_at < now() - interval '2 hours';
    GET DIAGNOSTICS requeued = ROW_COUNT;

    UPDATE public.snippets SET status = 'Ready for review'
    WHERE status = 'Reviewing' AND updated_at < now() - interval '2 hours';
    GET DIAGNOSTICS rereview = ROW_COUNT;

    RETURN jsonb_build_object('requeued', requeued, 'rereview', rereview);
END;
$function$;

-- Not an RPC: only the cron job (runs as postgres) and service_role may call it.
REVOKE EXECUTE ON FUNCTION public.sweep_stuck_snippets() FROM public, anon, authenticated;

-- pg_cron is platform-managed (see the baseline); skip the job where it is absent, e.g. a local reset.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_cron') THEN
        PERFORM cron.schedule('sweep_stuck_snippets', '5 * * * *', 'SELECT public.sweep_stuck_snippets()');
    END IF;
END $$;
