-- get_trending_topics: same output, ~cheaper sparkline.
--
-- What changed (behaviour is identical: same JSON shape, keys and ordering; verified on
-- production 2026-09-14 with 24 input combinations, see PR):
--  1. sparkline_data no longer does "label_counts CROSS JOIN time_buckets LEFT JOIN
--     snippet_labels LEFT JOIN filtered_snippets" with COUNT(DISTINCT CASE ...), which
--     re-joined every snippet of each top label once per bucket (10-31x the work). It now
--     aggregates the filtered snippets of the top labels once, each snippet landing in
--     exactly one bucket, and fills empty buckets with 0 via a LEFT JOIN from the
--     label x bucket grid.
--  2. Deterministic tiebreak: labels with equal counts are ordered by label id (both in the
--     LIMIT and in the returned array). The previous version left tie order to the planner,
--     so equal-count topics could swap places between calls.
--  3. states / sources filters use "= ANY(text[])" so the planner gets a real row estimate
--     and can use the audio_files indexes (see 20260915000200_add_audio_files_radio_station_code_index.sql).
--
-- Same signature, so CREATE OR REPLACE is enough; grants are preserved.
-- Rollback: supabase/database/sql/rollback/2026-09-14_get_trending_topics_before.sql

CREATE OR REPLACE FUNCTION public.get_trending_topics(p_timespan text DEFAULT '7d'::text, p_filter jsonb DEFAULT NULL::jsonb, p_language text DEFAULT 'english'::text, p_limit integer DEFAULT 10)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
AS $function$
DECLARE
    current_user_id UUID;
    result JSONB;
    time_start TIMESTAMPTZ;
    bucket_interval INTERVAL;
    num_buckets INTEGER;
    -- Pre-extracted filter arrays (NULL = filter not set). "col = ANY(text[])" gives the
    -- planner a usable row estimate, unlike "col IN (SELECT jsonb_array_elements_text(...))",
    -- so it can use the audio_files (radio_station_code, id) / (location_state) indexes.
    state_codes TEXT[] := CASE
        WHEN p_filter IS NOT NULL AND p_filter ? 'states' AND jsonb_array_length(p_filter->'states') > 0
        THEN ARRAY(SELECT jsonb_array_elements_text(p_filter->'states')) END;
    source_codes TEXT[] := CASE
        WHEN p_filter IS NOT NULL AND p_filter ? 'sources' AND jsonb_array_length(p_filter->'sources') > 0
        THEN ARRAY(SELECT jsonb_array_elements_text(p_filter->'sources')) END;
BEGIN
    -- Check if the user is authenticated
    current_user_id := auth.uid();
    IF current_user_id IS NULL THEN
        RAISE EXCEPTION 'Only logged-in users can call this function';
    END IF;

    -- Determine time window and bucket size based on timespan
    CASE p_timespan
        WHEN '24h' THEN
            time_start := NOW() - INTERVAL '24 hours';
            bucket_interval := INTERVAL '1 hour';
            num_buckets := 24;
        WHEN '7d' THEN
            time_start := NOW() - INTERVAL '7 days';
            bucket_interval := INTERVAL '1 day';
            num_buckets := 7;
        WHEN '30d' THEN
            time_start := NOW() - INTERVAL '30 days';
            bucket_interval := INTERVAL '1 day';
            num_buckets := 30;
        WHEN '90d' THEN
            time_start := NOW() - INTERVAL '90 days';
            bucket_interval := INTERVAL '9 days';
            num_buckets := 10;
        ELSE -- 'all' or default
            time_start := NOW() - INTERVAL '365 days';
            bucket_interval := INTERVAL '30 days';
            num_buckets := 12;
    END CASE;

    WITH
    -- Pre-compute hidden snippet IDs (small set to exclude via LEFT JOIN)
    hidden_snippets AS (
        SELECT DISTINCT snippet FROM user_hide_snippets
    ),
    -- Filter snippets based on provided filters (optimized with LEFT JOIN instead of NOT EXISTS)
    filtered_snippets AS (
        SELECT s.id, s.recorded_at
        FROM snippets s
        LEFT JOIN audio_files a ON s.audio_file = a.id
        LEFT JOIN hidden_snippets hs ON hs.snippet = s.id
        WHERE s.status = 'Processed'
        AND (s.confidence_scores->>'overall')::INTEGER >= 95
        AND s.recorded_at >= time_start
        -- Exclude hidden snippets via JOIN (faster than NOT EXISTS)
        AND hs.snippet IS NULL
        -- Language filter
        AND (
            p_filter IS NULL OR
            NOT p_filter ? 'languages' OR
            jsonb_array_length(p_filter->'languages') = 0 OR
            s.language ->> 'primary_language' IN (SELECT jsonb_array_elements_text(p_filter->'languages'))
        )
        -- State filter
        AND (state_codes IS NULL OR a.location_state = ANY(state_codes))
        -- Source filter
        AND (source_codes IS NULL OR a.radio_station_code = ANY(source_codes))
        -- Political spectrum filter
        AND (
            p_filter IS NULL OR
            NOT p_filter ? 'politicalSpectrum' OR
            (
                CASE
                    WHEN p_filter->>'politicalSpectrum' = 'left' THEN (s.political_leaning->>'score')::FLOAT BETWEEN -1.0 AND -0.7
                    WHEN p_filter->>'politicalSpectrum' = 'center-left' THEN (s.political_leaning->>'score')::FLOAT BETWEEN -0.7 AND -0.3
                    WHEN p_filter->>'politicalSpectrum' = 'center' THEN (s.political_leaning->>'score')::FLOAT BETWEEN -0.3 AND 0.3
                    WHEN p_filter->>'politicalSpectrum' = 'center-right' THEN (s.political_leaning->>'score')::FLOAT BETWEEN 0.3 AND 0.7
                    WHEN p_filter->>'politicalSpectrum' = 'right' THEN (s.political_leaning->>'score')::FLOAT BETWEEN 0.7 AND 1.0
                    ELSE TRUE
                END
            )
        )
    ),
    -- Get label counts from filtered snippets
    label_counts AS (
        SELECT
            l.id AS label_id,
            CASE
                WHEN p_language = 'spanish' THEN COALESCE(l.text_spanish, l.text)
                ELSE l.text
            END AS label_text,
            COUNT(DISTINCT sl.snippet) AS snippet_count
        FROM snippet_labels sl
        JOIN labels l ON sl.label = l.id
        JOIN filtered_snippets fs ON sl.snippet = fs.id
        GROUP BY l.id, l.text, l.text_spanish
        ORDER BY snippet_count DESC, l.id
        LIMIT p_limit
    ),
    -- Generate time buckets for sparkline
    time_buckets AS (
        SELECT generate_series(
            date_trunc(
                CASE WHEN p_timespan = '24h' THEN 'hour' ELSE 'day' END,
                time_start
            ),
            date_trunc(
                CASE WHEN p_timespan = '24h' THEN 'hour' ELSE 'day' END,
                NOW()
            ),
            bucket_interval
        ) AS bucket_start
    ),
    -- Sparkline: aggregate ONCE over the (small) filtered set for the top labels,
    -- assigning each snippet to exactly one bucket; then fill missing buckets with 0
    -- via LEFT JOIN from the full label x bucket grid. (Replaces CROSS JOIN time_buckets
    -- + COUNT(DISTINCT CASE ...), which re-scanned snippet_labels once per bucket.)
    bucket_counts AS (
        SELECT
            sl.label AS label_id,
            tb.bucket_start,
            COUNT(DISTINCT fs.id) AS count
        FROM filtered_snippets fs
        JOIN snippet_labels sl ON sl.snippet = fs.id
        JOIN label_counts lc ON lc.label_id = sl.label
        JOIN time_buckets tb
          ON fs.recorded_at >= tb.bucket_start
         AND fs.recorded_at <  tb.bucket_start + bucket_interval
        GROUP BY sl.label, tb.bucket_start
    ),
    sparkline_data AS (
        SELECT
            lc.label_id,
            tb.bucket_start,
            COALESCE(bc.count, 0) AS count
        FROM label_counts lc
        CROSS JOIN time_buckets tb
        LEFT JOIN bucket_counts bc
               ON bc.label_id = lc.label_id
              AND bc.bucket_start = tb.bucket_start
    ),
    -- Aggregate sparkline data per label
    sparkline_agg AS (
        SELECT
            label_id,
            jsonb_agg(count ORDER BY bucket_start) AS sparkline
        FROM sparkline_data
        GROUP BY label_id
    )
    -- Build final result
    SELECT jsonb_build_object(
        'timespan', p_timespan,
        'topics', COALESCE(
            jsonb_agg(
                jsonb_build_object(
                    'id', lc.label_id,
                    'text', lc.label_text,
                    'count', lc.snippet_count,
                    'sparkline', COALESCE(sa.sparkline, '[]'::jsonb)
                )
                ORDER BY lc.snippet_count DESC, lc.label_id
            ),
            '[]'::jsonb
        )
    ) INTO result
    FROM label_counts lc
    LEFT JOIN sparkline_agg sa ON lc.label_id = sa.label_id;

    RETURN COALESCE(result, jsonb_build_object('timespan', p_timespan, 'topics', '[]'::jsonb));
END;
$function$
;

GRANT EXECUTE ON FUNCTION public.get_trending_topics(text, jsonb, text, integer) TO anon, authenticated, service_role;
