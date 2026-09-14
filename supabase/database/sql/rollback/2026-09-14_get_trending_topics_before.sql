-- Rollback: live definition of public.get_trending_topics captured 2026-09-14 from production
-- (before the 20260914_* migrations). Re-run this file to restore the previous version.
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
        AND (
            p_filter IS NULL OR
            NOT p_filter ? 'states' OR
            jsonb_array_length(p_filter->'states') = 0 OR
            a.location_state IN (SELECT jsonb_array_elements_text(p_filter->'states'))
        )
        -- Source filter
        AND (
            p_filter IS NULL OR
            NOT p_filter ? 'sources' OR
            jsonb_array_length(p_filter->'sources') = 0 OR
            a.radio_station_code IN (SELECT jsonb_array_elements_text(p_filter->'sources'))
        )
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
        ORDER BY snippet_count DESC
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
    -- Get sparkline data for top labels - count snippets per bucket
    sparkline_data AS (
        SELECT
            lc.label_id,
            tb.bucket_start,
            COUNT(DISTINCT CASE
                WHEN fs.recorded_at >= tb.bucket_start
                AND fs.recorded_at < tb.bucket_start + bucket_interval
                THEN fs.id
            END) AS count
        FROM label_counts lc
        CROSS JOIN time_buckets tb
        LEFT JOIN snippet_labels sl ON sl.label = lc.label_id
        LEFT JOIN filtered_snippets fs ON sl.snippet = fs.id
        GROUP BY lc.label_id, tb.bucket_start
        ORDER BY lc.label_id, tb.bucket_start
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
                ORDER BY lc.snippet_count DESC
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
