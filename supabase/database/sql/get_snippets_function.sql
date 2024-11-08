CREATE
OR REPLACE FUNCTION get_snippets (
    page INTEGER DEFAULT 0,
    page_size INTEGER DEFAULT 10,
    p_language TEXT DEFAULT 'english',
    p_filter JSONB DEFAULT '{}'::jsonb
) RETURNS jsonb SECURITY DEFINER AS $$
DECLARE
    current_user_id UUID;
    result jsonb;
    total_count INTEGER;
    total_pages INTEGER;
BEGIN
    -- Check if the user is authenticated
    current_user_id := auth.uid();
    IF current_user_id IS NULL THEN
        RAISE EXCEPTION 'Only logged-in users can call this function';
    END IF;

    CREATE TEMP TABLE filtered_snippets AS
        SELECT
            s.id,
            s.recorded_at,
            s.duration,
            s.start_time,
            s.end_time,
            s.file_path,
            s.file_size,
            s.political_leaning,
            CASE
                WHEN p_language = 'spanish' THEN s.title ->> 'spanish'
                ELSE s.title ->> 'english'
            END AS title,
            CASE
                WHEN p_language = 'spanish' THEN s.summary ->> 'spanish'
                ELSE s.summary ->> 'english'
            END AS summary,
            CASE
                WHEN p_language = 'spanish' THEN s.explanation ->> 'spanish'
                ELSE s.explanation ->> 'english'
            END AS explanation,
            s.confidence_scores,
            s.language,
            s.context,
            (get_snippet_labels(s.id, p_language) -> 'labels') AS labels,
            jsonb_build_object(
                'id', a.id,
                'radio_station_name', a.radio_station_name,
                'radio_station_code', a.radio_station_code,
                'location_state', a.location_state,
                'location_city', a.location_city
            ) AS audio_file,
            CASE
                WHEN us.id IS NOT NULL THEN true
                ELSE false
            END AS starred_by_user,
            ul.value AS user_like_status
        FROM snippets s
        LEFT JOIN audio_files a ON s.audio_file = a.id
        LEFT JOIN user_star_snippets us ON us.snippet = s.id AND us."user" = current_user_id
        LEFT JOIN user_like_snippets ul ON ul.snippet = s.id AND ul."user" = current_user_id
        WHERE s.status = 'Processed' AND (s.confidence_scores->>'overall')::INTEGER >= 95
        AND (
            p_filter IS NULL OR
            NOT p_filter ? 'languages' OR
            jsonb_array_length(p_filter->'languages') = 0 OR
            s.language ->> 'primary_language' IN (SELECT jsonb_array_elements_text(p_filter->'languages'))
        )
        AND (
            p_filter IS NULL OR
            NOT p_filter ? 'states' OR
            jsonb_array_length(p_filter->'states') = 0 OR
            a.location_state IN (SELECT jsonb_array_elements_text(p_filter->'states'))
        )
        AND (
            p_filter IS NULL OR
            NOT p_filter ? 'sources' OR
            jsonb_array_length(p_filter->'sources') = 0 OR
            a.radio_station_code IN (SELECT jsonb_array_elements_text(p_filter->'sources'))
        )
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
        AND (
            p_filter IS NULL OR
            NOT p_filter ? 'labeledBy' OR
            (
                CASE
                    WHEN jsonb_array_length(p_filter->'labeledBy') = 0 THEN TRUE
                    ELSE (
                        CASE
                            WHEN (
                                p_filter->'labeledBy' ? 'by_me' AND
                                p_filter->'labeledBy' ? 'by_others'
                            ) THEN
                                EXISTS (
                                    SELECT 1
                                    FROM label_upvotes lu
                                    JOIN snippet_labels sl ON lu.snippet_label = sl.id
                                    WHERE sl.snippet = s.id
                                )
                            WHEN p_filter->'labeledBy' ? 'by_me' THEN
                                EXISTS (
                                    SELECT 1
                                    FROM label_upvotes lu
                                    JOIN snippet_labels sl ON lu.snippet_label = sl.id
                                    WHERE sl.snippet = s.id
                                    AND lu.upvoted_by = current_user_id
                                )
                            WHEN p_filter->'labeledBy' ? 'by_others' THEN
                                EXISTS (
                                    SELECT 1
                                    FROM label_upvotes lu
                                    JOIN snippet_labels sl ON lu.snippet_label = sl.id
                                    WHERE sl.snippet = s.id
                                    AND lu.upvoted_by != current_user_id
                                )
                            ELSE FALSE
                        END
                    )
                END
            )
        )
        AND (
            p_filter IS NULL OR
            NOT p_filter ? 'starredBy' OR
            (
                CASE
                    WHEN jsonb_array_length(p_filter->'starredBy') = 0 THEN TRUE
                    ELSE (
                        CASE
                            WHEN (
                                p_filter->'starredBy' ? 'by_me' AND
                                p_filter->'starredBy' ? 'by_others'
                            ) THEN
                                EXISTS (
                                    SELECT 1
                                    FROM user_star_snippets uss
                                    WHERE uss.snippet = s.id
                                )
                            WHEN p_filter->'starredBy' ? 'by_me' THEN
                                EXISTS (
                                    SELECT 1
                                    FROM user_star_snippets uss
                                    WHERE uss.snippet = s.id
                                    AND uss."user" = current_user_id
                                )
                            WHEN p_filter->'starredBy' ? 'by_others' THEN
                                EXISTS (
                                    SELECT 1
                                    FROM user_star_snippets uss
                                    WHERE uss.snippet = s.id
                                    AND uss."user" != current_user_id
                                )
                            ELSE FALSE
                        END
                    )
                END
            )
        )
        AND (
            p_filter IS NULL OR
            NOT p_filter ? 'labels' OR
            jsonb_array_length(p_filter->'labels') = 0 OR
            EXISTS (
                SELECT 1
                FROM snippet_labels sl
                WHERE sl.snippet = s.id
                AND sl.label IN (
                    SELECT (jsonb_array_elements_text(p_filter->'labels'))::UUID
                )
            )
        )
        ORDER BY s.recorded_at DESC;

    -- Get total count
    SELECT COUNT(*) INTO total_count
    FROM filtered_snippets;

    -- Get paginated results
    SELECT jsonb_agg(fs.*) INTO result
    FROM (
        SELECT * FROM filtered_snippets
        LIMIT page_size
        OFFSET page * page_size
    ) fs;

    -- Clean up
    DROP TABLE filtered_snippets;

    -- Calculate total pages after getting the filtered count
    total_pages := CEIL(total_count::FLOAT / page_size);

    RETURN jsonb_build_object(
        'num_of_snippets', COALESCE(jsonb_array_length(result), 0),
        'snippets', COALESCE(result, '[]'::jsonb),
        'current_page', page,
        'page_size', page_size,
        'total_pages', total_pages
    );
END;
$$ LANGUAGE plpgsql;
