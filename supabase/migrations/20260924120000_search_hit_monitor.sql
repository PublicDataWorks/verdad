-- VER-402: hourly search hit share of live analyses (recorded in the last 7 days; old reprocessed claims hit less
-- for reasons unrelated to search). Posts to Slack when it stays low two hours running; the webhook URL lives in
-- Vault as ops_alerts_slack_webhook, so switching channels needs no migration.
-- Rollback: SELECT cron.unschedule('record_search_hit_stats');
--           DROP FUNCTION public.record_search_hit_stats(timestamptz, boolean, numeric, integer);
--           DROP TABLE public.search_hit_stats;

CREATE TABLE IF NOT EXISTS public.search_hit_stats (
    hour_start TIMESTAMPTZ PRIMARY KEY,
    analyses INTEGER NOT NULL,
    analyses_with_search INTEGER NOT NULL,
    analyses_with_hit INTEGER NOT NULL,
    queries INTEGER NOT NULL,
    queries_with_hit INTEGER NOT NULL,
    stage4_searches INTEGER NOT NULL,
    stage4_searches_with_results INTEGER NOT NULL,
    alerted BOOLEAN NOT NULL DEFAULT false,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE public.search_hit_stats ENABLE ROW LEVEL SECURITY;
GRANT ALL ON TABLE public.search_hit_stats TO service_role;

CREATE OR REPLACE FUNCTION public.record_search_hit_stats(
    p_hour timestamptz DEFAULT date_trunc('hour', now()) - interval '1 hour',
    p_alert boolean DEFAULT true,
    p_min_share numeric DEFAULT 0.60,
    p_min_analyses integer DEFAULT 20)
 RETURNS jsonb
 LANGUAGE plpgsql
 STRICT
 SET search_path = ''
AS $function$
DECLARE
    v_row public.search_hit_stats;
    v_prev public.search_hit_stats;
    v_was_alerted boolean;
    v_bad boolean;
    v_prev_bad boolean;
    v_url text;
BEGIN
    v_row.hour_start := date_trunc('hour', p_hour);

    WITH g AS (
        SELECT coalesce(gm->'searches_performed', gm->'stage_3_verification_evidence'->'searches_performed') AS sp,
               gm->'stage_4_citation_check'->'retrieval' AS s4
        FROM (SELECT s.grounding_metadata::jsonb AS gm
              FROM public.snippets s
              WHERE s.status = 'Processed'
                AND s.recorded_at >= v_row.hour_start - interval '7 days'
                AND s.updated_at >= v_row.hour_start AND s.updated_at < v_row.hour_start + interval '1 hour'
                AND left(s.grounding_metadata, 1) = '{') r
    ), a AS (
        SELECT sp, s4,
               (SELECT count(*) FILTER (WHERE e->>'result_status' = 'results_found') FROM jsonb_array_elements(sp) e) AS hits
        FROM (SELECT CASE WHEN jsonb_typeof(sp) = 'array' THEN sp ELSE '[]'::jsonb END AS sp, s4 FROM g) x
    )
    SELECT count(*), count(*) FILTER (WHERE jsonb_array_length(sp) > 0), count(*) FILTER (WHERE hits > 0),
           coalesce(sum(jsonb_array_length(sp)), 0), coalesce(sum(hits), 0),
           coalesce(sum((s4->>'searches')::integer), 0), coalesce(sum((s4->>'searches_with_results')::integer), 0)
    INTO v_row.analyses, v_row.analyses_with_search, v_row.analyses_with_hit, v_row.queries, v_row.queries_with_hit,
         v_row.stage4_searches, v_row.stage4_searches_with_results
    FROM a;

    SELECT alerted INTO v_was_alerted FROM public.search_hit_stats WHERE hour_start = v_row.hour_start;
    SELECT * INTO v_prev FROM public.search_hit_stats WHERE hour_start = v_row.hour_start - interval '1 hour';
    v_bad := v_row.analyses >= p_min_analyses AND v_row.analyses_with_hit < p_min_share * v_row.analyses;
    v_prev_bad := coalesce(v_prev.analyses >= p_min_analyses AND v_prev.analyses_with_hit < p_min_share * v_prev.analyses, false);
    -- One alert per streak: an hour after an alerted hour inherits the flag instead of posting again.
    v_row.alerted := v_bad AND (v_prev_bad OR coalesce(v_prev.alerted, false));
    v_row.recorded_at := now();

    IF v_row.alerted AND NOT coalesce(v_prev.alerted, false) AND NOT coalesce(v_was_alerted, false) AND p_alert THEN
        SELECT decrypted_secret INTO v_url FROM vault.decrypted_secrets WHERE name = 'ops_alerts_slack_webhook';
        IF v_url IS NULL THEN
            RAISE NOTICE 'search hit share low for % but vault secret ops_alerts_slack_webhook is missing', v_row.hour_start;
        ELSE
            PERFORM net.http_post(url := v_url, body := jsonb_build_object('text', format(
                'Search monitor: Stage 3 search hit share was %s%% (%s of %s analyses) for the hour from %s UTC and %s%% the hour before, under %s%% two hours running. Check the SearXNG engines (VER-390, VER-400).',
                round(100.0 * v_row.analyses_with_hit / v_row.analyses), v_row.analyses_with_hit, v_row.analyses,
                to_char(v_row.hour_start AT TIME ZONE 'utc', 'YYYY-MM-DD HH24:MI'),
                round(100.0 * v_prev.analyses_with_hit / v_prev.analyses), round(100 * p_min_share))));
        END IF;
    END IF;

    INSERT INTO public.search_hit_stats VALUES (v_row.*)
    ON CONFLICT (hour_start) DO UPDATE SET
        analyses = EXCLUDED.analyses, analyses_with_search = EXCLUDED.analyses_with_search,
        analyses_with_hit = EXCLUDED.analyses_with_hit, queries = EXCLUDED.queries,
        queries_with_hit = EXCLUDED.queries_with_hit, stage4_searches = EXCLUDED.stage4_searches,
        stage4_searches_with_results = EXCLUDED.stage4_searches_with_results,
        alerted = EXCLUDED.alerted, recorded_at = EXCLUDED.recorded_at;
    RETURN to_jsonb(v_row);
END;
$function$;

COMMENT ON FUNCTION public.record_search_hit_stats(timestamptz, boolean, numeric, integer) IS
    'VER-402: upsert search_hit_stats for one hour (default the last full hour); Slack alert via Vault webhook when the share of analyses with a search hit stays under p_min_share for two hours. Backfill with p_alert => false.';

-- Not an RPC: only the cron job (runs as postgres) and service_role may call it.
REVOKE EXECUTE ON FUNCTION public.record_search_hit_stats(timestamptz, boolean, numeric, integer) FROM public, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.record_search_hit_stats(timestamptz, boolean, numeric, integer) TO service_role;

-- pg_cron is platform-managed (see the baseline); skip the job where it is absent, e.g. a local reset.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_cron') THEN
        PERFORM cron.schedule('record_search_hit_stats', '7 * * * *', 'SELECT public.record_search_hit_stats()');
    END IF;
END $$;
