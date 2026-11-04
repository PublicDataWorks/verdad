-- VER-454 item 2: Stage 3 reserves New snippets by priority (live, Tier A backlog, ranked station-hours, rest),
-- then newest first. A trigger scores each snippet as it enters New, so Stage 2 needs no code change or deploy; an
-- hourly job re-scores waiting live rows once they pass 48 h, so a Stage 3 pause or backlog cannot keep them on top.
--
-- Priority, first rule that matches:
--   4  recorded within the last 48 h, or recorded 2026-11-03 to 2026-11-05 UTC (election days, VER-454 Tier 0)
--   3  station tier A in station_priority
--   2  station_hour_priority has the station's local day of week and hour of recorded_at
--   1  everything else (unknown station, null timezone, null recorded_at)
-- station_hour_priority ships empty; after loading a ranking, re-score waiting rows with the backfill UPDATE below.
--
-- Apply in one Management API request (one transaction), then 20261104100100 (index). The backfill reads New rows
-- through idx_snippets_status_not_processed and fires snippets_handle_updated_at on each; harmless, since
-- sweep_stuck_snippets keys on Processing/Reviewing only.
-- Rollback: restore ORDER BY recorded_at DESC in fetch_a_new_snippet_and_reserve_it (both copies), then
-- DROP TRIGGER snippets_set_priority ON public.snippets and SELECT cron.unschedule('demote_stale_live_snippets').
-- Column and tables are inert without them.

SET lock_timeout = '3s';

CREATE TABLE IF NOT EXISTS public.station_priority (
    radio_station_code text PRIMARY KEY,
    tier text NOT NULL CHECK (tier IN ('A', 'B', 'C')),
    timezone text
);
COMMENT ON COLUMN public.station_priority.tier IS
    'VER-454 station tier. Only A changes a snippet priority; B and C record the ticket''s station lists.';
COMMENT ON COLUMN public.station_priority.timezone IS
    'IANA timezone of the station clock, read only for station_hour_priority lookups.';

CREATE TABLE IF NOT EXISTS public.station_hour_priority (
    radio_station_code text NOT NULL REFERENCES public.station_priority ON DELETE CASCADE,
    day_of_week smallint NOT NULL CHECK (day_of_week BETWEEN 0 AND 6),
    local_hour smallint NOT NULL CHECK (local_hour BETWEEN 0 AND 23),
    PRIMARY KEY (radio_station_code, day_of_week, local_hour)
);
COMMENT ON TABLE public.station_hour_priority IS
    'Ranked station-hours (VER-454): a row ranks that local hour. day_of_week 0 = Sunday, as extract(dow).';

ALTER TABLE public.station_priority ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.station_hour_priority ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.station_priority, public.station_hour_priority FROM anon, authenticated;
GRANT ALL ON TABLE public.station_priority, public.station_hour_priority TO service_role;

-- Stations seen in audio_files 2026-10-21 to 2026-11-04; timezones from location_state, web-checked where it gives none.
INSERT INTO public.station_priority (radio_station_code, tier, timezone) VALUES
    ('ARAB', 'C', 'America/Detroit'),
    ('K229DB - 93.7 FM', 'C', 'America/Phoenix'),
    ('KABA - 90.3 FM', 'C', 'America/Chicago'),
    ('KBIC - 105.7 FM', 'C', 'America/Chicago'),
    ('KBNL - 89.9 FM', 'C', 'America/Chicago'),
    ('KCKO - 107.9 FM', 'C', 'America/Phoenix'),
    ('KCMT - 92.1 FM', 'C', 'America/Phoenix'),
    ('KHEM - 89.3 FM', 'A', 'America/Chicago'),
    ('KHOT - 105.9 FM', 'C', 'America/Phoenix'),
    ('KISF - 103.5 FM', 'C', 'America/Los_Angeles'),
    ('KMMA - 97.1 FM', 'C', 'America/Phoenix'),
    ('KNOG - 91.7 FM', 'C', 'America/Phoenix'),
    ('KRGT - 99.3 FM', 'C', 'America/Los_Angeles'),
    ('KRMC - 91.7 FM', 'C', 'America/Phoenix'),
    ('KVIV - 1340 AM', 'B', 'America/Chicago'),
    ('KVNR', 'B', 'America/Los_Angeles'),
    ('KWST - 1430 AM', 'C', 'America/Phoenix'),
    ('KYAR - 98.3 FM', 'C', 'America/Chicago'),
    ('KZLZ - 105.3 FM', 'C', 'America/Phoenix'),
    ('MCD', 'C', 'Europe/Paris'),
    ('RUMBA 4451', 'C', 'America/Phoenix'),
    ('SPMN', 'A', NULL),
    ('WACC - 830 AM', 'C', 'America/New_York'),
    ('WADO - 1280 AM', 'B', 'America/New_York'),
    ('WAQI - 710 AM', 'B', 'America/New_York'),
    ('WAXY - 790 AM', 'A', 'America/New_York'),
    ('WBZW - 96.7 FM', 'C', 'America/New_York'),
    ('WBZY - 105.7 FM', 'C', 'America/New_York'),
    ('WDTW - 1310 AM', 'C', 'America/Detroit'),
    ('WGOS', 'C', 'America/New_York'),
    ('WIST', 'C', 'America/New_York'),
    ('WKAQ - 580 AM', 'B', 'America/Puerto_Rico'),
    ('WLAZ - 89.1 FM', 'C', 'America/New_York'),
    ('WLCH - 91.3 FM', 'C', 'America/New_York'),
    ('WLEL - 94.3 FM', 'C', 'America/New_York'),
    ('WLMV - 1480 AM', 'C', 'America/Chicago'),
    ('WMUZ - 1200 AM', 'A', 'America/Detroit'),
    ('WNMA - 1210 AM', 'A', 'America/New_York'),
    ('WOAP - 1080 AM', 'C', 'America/Detroit'),
    ('WPHE - 690 AM', 'C', 'America/New_York'),
    ('WRUM - 100.3 FM', 'C', 'America/New_York'),
    ('WRUM HD2 - 97.1 FM', 'C', 'America/New_York'),
    ('WSDS - 1480 AM', 'C', 'America/Detroit'),
    ('WSGH', 'C', 'America/New_York'),
    ('WSRF - 99.5 FM', 'B', 'America/New_York'),
    ('WSRP', 'C', 'America/New_York'),
    ('WSUA - 1260 AM', 'B', 'America/New_York'),
    ('WUMR - 106.1 FM', 'C', 'America/New_York'),
    ('WWFE - 670 AM', 'A', 'America/New_York'),
    ('WZHF', 'A', 'America/New_York'),
    ('WZTU - 94.9 FM', 'C', 'America/New_York'),
    ('XEKAM - 950 AM', 'B', 'America/Tijuana'),
    ('XEMX - 1120 AM', 'A', 'America/Tijuana'),
    ('XEZOL - 860 AM', 'B', 'America/Ciudad_Juarez')
ON CONFLICT (radio_station_code) DO NOTHING;

ALTER TABLE public.snippets
    ADD COLUMN IF NOT EXISTS priority smallint NOT NULL DEFAULT 1;
COMMENT ON COLUMN public.snippets.priority IS
    'Stage 3 reserve order (VER-454): 4 live, 3 tier A, 2 ranked station-hour, 1 rest. Set by public.snippet_priority() when a row enters New.';

CREATE OR REPLACE FUNCTION public.snippet_priority(p_audio_file uuid, p_recorded_at timestamptz)
 RETURNS smallint
 LANGUAGE plpgsql
 STABLE
 SECURITY INVOKER
 SET search_path = ''
AS $function$
DECLARE
    v_station text;
    v_tier text;
    v_timezone text;
    v_local timestamp;
BEGIN
    IF p_recorded_at IS NULL THEN
        RETURN 1;
    END IF;
    IF p_recorded_at >= now() - interval '48 hours'
       OR (p_recorded_at >= '2026-11-03 00:00+00' AND p_recorded_at < '2026-11-05 00:00+00') THEN
        RETURN 4;
    END IF;

    SELECT sp.radio_station_code, sp.tier, sp.timezone
    INTO v_station, v_tier, v_timezone
    FROM public.audio_files af
    JOIN public.station_priority sp ON sp.radio_station_code = af.radio_station_code
    WHERE af.id = p_audio_file;

    IF v_tier = 'A' THEN
        RETURN 3;
    END IF;
    IF v_timezone IS NULL THEN
        RETURN 1;
    END IF;

    -- A bad timezone string must cost a priority, never a Stage 2 insert.
    BEGIN
        v_local := p_recorded_at AT TIME ZONE v_timezone;
    EXCEPTION WHEN invalid_parameter_value THEN
        RETURN 1;
    END;

    IF EXISTS (
        SELECT 1
        FROM public.station_hour_priority shp
        WHERE shp.radio_station_code = v_station
          AND shp.day_of_week = extract(dow FROM v_local)
          AND shp.local_hour = extract(hour FROM v_local)
    ) THEN
        RETURN 2;
    END IF;
    RETURN 1;
END;
$function$;

REVOKE EXECUTE ON FUNCTION public.snippet_priority(uuid, timestamptz) FROM public, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.snippet_priority(uuid, timestamptz) TO service_role;

CREATE OR REPLACE FUNCTION public.snippets_set_priority()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY INVOKER
 SET search_path = ''
AS $function$
BEGIN
    IF NEW.status = 'New' AND (TG_OP = 'INSERT' OR OLD.status IS DISTINCT FROM 'New') THEN
        NEW.priority := public.snippet_priority(NEW.audio_file, NEW.recorded_at);
    END IF;
    RETURN NEW;
END;
$function$;

DROP TRIGGER IF EXISTS snippets_set_priority ON public.snippets;
CREATE TRIGGER snippets_set_priority
    BEFORE INSERT OR UPDATE OF status ON public.snippets
    FOR EACH ROW
    EXECUTE FUNCTION public.snippets_set_priority();

CREATE OR REPLACE FUNCTION public.demote_stale_live_snippets()
 RETURNS integer
 LANGUAGE plpgsql
 SECURITY INVOKER
 SET search_path = ''
AS $function$
DECLARE
    demoted integer;
BEGIN
    UPDATE public.snippets s
    SET priority = public.snippet_priority(s.audio_file, s.recorded_at)
    WHERE s.status = 'New'
      AND s.priority = 4
      AND s.recorded_at < now() - interval '48 hours'
      AND public.snippet_priority(s.audio_file, s.recorded_at) <> 4;
    GET DIAGNOSTICS demoted = ROW_COUNT;
    RETURN demoted;
END;
$function$;

REVOKE EXECUTE ON FUNCTION public.demote_stale_live_snippets() FROM public, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.demote_stale_live_snippets() TO service_role;

-- pg_cron is absent on a local reset; skip the job there.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_cron') THEN
        PERFORM cron.schedule('demote_stale_live_snippets', '47 * * * *', 'SELECT public.demote_stale_live_snippets()');
    END IF;
END $$;

-- Only the ORDER BY changes. The result gains a priority key; Stage 3 reads named keys only.
CREATE OR REPLACE FUNCTION public.fetch_a_new_snippet_and_reserve_it()
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY INVOKER
AS $function$
DECLARE
    snippet_record jsonb;
BEGIN
    UPDATE public.snippets
    SET status = 'Processing'
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

UPDATE public.snippets
SET priority = public.snippet_priority(audio_file, recorded_at)
WHERE status = 'New';

RESET lock_timeout;
