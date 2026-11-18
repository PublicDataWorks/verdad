-- VER-487: prefix the stall alert with ❌ so it reads as a problem at a glance; the rest of the function is
-- unchanged from 20261117100000. Rollback: re-run the function from 20261117100000.

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
        v_text := format('❌ Stage 1 monitor: no recording finished Stage 1 since %s UTC (%s min). Recordings waiting: %s. Check the GPU box worker.',
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
