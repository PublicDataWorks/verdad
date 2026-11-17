-- VER-487: Slack alert when Stage 1 stalls: recordings wait and none finished for p_stall_minutes. One post per
-- stall and one when a recording finishes again, through the search monitor's Vault webhook (VER-402).
-- Rollback: SELECT cron.unschedule('check_stage1_stall');
--           DROP FUNCTION public.check_stage1_stall(integer, integer, boolean);
--           DROP TABLE public.stage1_stall_alerts;

CREATE TABLE IF NOT EXISTS public.stage1_stall_alerts (
    stalled_since TIMESTAMPTZ PRIMARY KEY,
    alerted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    waiting INTEGER NOT NULL,
    recovered_at TIMESTAMPTZ
);
ALTER TABLE public.stage1_stall_alerts ENABLE ROW LEVEL SECURITY;
GRANT ALL ON TABLE public.stage1_stall_alerts TO service_role;

CREATE OR REPLACE FUNCTION public.check_stage1_stall(
    p_stall_minutes integer DEFAULT 60,
    p_min_waiting integer DEFAULT 1,
    p_alert boolean DEFAULT true)
 RETURNS jsonb
 LANGUAGE plpgsql
 STRICT
 SET search_path = ''
AS $function$
DECLARE
    v_now timestamptz := now();
    v_stall interval := make_interval(mins => p_stall_minutes);
    v_waiting integer;
    v_last_done timestamptz;
    v_oldest_waiting timestamptz;
    v_open public.stage1_stall_alerts;
    v_recovering boolean;
    v_since timestamptz;
    v_text text;
    v_url text;
BEGIN
    -- Waiting = arrived over v_stall ago and not finished; younger rows are normal queue.
    SELECT count(*) FILTER (WHERE a.status IN ('New', 'Processing') AND a.created_at < v_now - v_stall),
           max(a.updated_at) FILTER (WHERE a.status = 'Processed'),
           min(a.created_at) FILTER (WHERE a.status IN ('New', 'Processing'))
    INTO v_waiting, v_last_done, v_oldest_waiting
    FROM public.audio_files a
    WHERE a.recorded_at >= v_now - interval '24 hours';

    SELECT * INTO v_open FROM public.stage1_stall_alerts WHERE recovered_at IS NULL;
    v_recovering := FOUND;

    IF v_recovering THEN
        IF NOT coalesce(v_last_done > v_open.stalled_since, false) THEN
            RETURN jsonb_build_object('state', 'stalled', 'posted', false, 'waiting', v_waiting);
        END IF;
        v_text := format('Stage 1 monitor: Stage 1 finishes recordings again since %s UTC, after %s min. Recordings still waiting: %s.',
            to_char(v_last_done AT TIME ZONE 'utc', 'YYYY-MM-DD HH24:MI'),
            round(extract(epoch FROM v_last_done - v_open.stalled_since) / 60), v_waiting);
    ELSE
        IF NOT (v_waiting >= p_min_waiting AND (v_last_done IS NULL OR v_last_done < v_now - v_stall)) THEN
            RETURN jsonb_build_object('state', 'ok', 'posted', false, 'waiting', v_waiting);
        END IF;
        v_since := coalesce(v_last_done, v_oldest_waiting, v_now);
        v_text := format('Stage 1 monitor: no recording finished Stage 1 since %s UTC (%s min). Recordings waiting: %s. Check the GPU box worker.',
            to_char(v_since AT TIME ZONE 'utc', 'YYYY-MM-DD HH24:MI'),
            round(extract(epoch FROM v_now - v_since) / 60), v_waiting);
    END IF;

    IF p_alert THEN
        SELECT decrypted_secret INTO v_url FROM vault.decrypted_secrets WHERE name = 'ops_alerts_slack_webhook';
    END IF;
    IF v_url IS NULL THEN
        -- Nothing recorded, so the next run posts once the secret exists; a dry run stops here too.
        IF p_alert THEN
            RAISE NOTICE 'vault secret ops_alerts_slack_webhook is missing; not posted: %', v_text;
        END IF;
        RETURN jsonb_build_object('state', CASE WHEN v_recovering THEN 'recovered' ELSE 'stalled' END,
                                  'posted', false, 'waiting', v_waiting, 'text', v_text);
    END IF;

    PERFORM net.http_post(url := v_url, body := jsonb_build_object('text', v_text));
    IF v_recovering THEN
        UPDATE public.stage1_stall_alerts SET recovered_at = v_last_done WHERE stalled_since = v_open.stalled_since;
    ELSE
        INSERT INTO public.stage1_stall_alerts (stalled_since, alerted_at, waiting) VALUES (v_since, v_now, v_waiting);
    END IF;
    RETURN jsonb_build_object('state', CASE WHEN v_recovering THEN 'recovered' ELSE 'stalled' END,
                              'posted', true, 'waiting', v_waiting, 'text', v_text);
END;
$function$;

COMMENT ON FUNCTION public.check_stage1_stall(integer, integer, boolean) IS
    'VER-487: Slack alert via Vault webhook when Stage 1 recordings wait and none finished for p_stall_minutes; one post per stall, one on recovery. p_alert => false is a dry run.';

-- Not an RPC: only the cron job (runs as postgres) and service_role may call it.
REVOKE EXECUTE ON FUNCTION public.check_stage1_stall(integer, integer, boolean) FROM public, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.check_stage1_stall(integer, integer, boolean) TO service_role;

-- pg_cron is platform-managed (see the baseline); skip the job where it is absent, e.g. a local reset.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_cron') THEN
        PERFORM cron.schedule('check_stage1_stall', '4,19,34,49 * * * *', 'SELECT public.check_stage1_stall()');
    END IF;
END $$;
