DROP FUNCTION IF EXISTS get_snippets;

CREATE OR REPLACE FUNCTION get_snippets (
    p_language text,
    p_filter jsonb,
    page INTEGER,
    page_size INTEGER,
    p_order_by text,
    p_search_term text DEFAULT ''
) RETURNS jsonb SECURITY DEFINER AS $$
DECLARE
    current_user_id UUID;
    result jsonb;
    total_count INTEGER;
    total_pages INTEGER;
    user_roles TEXT[];
    user_is_admin BOOLEAN;
    trimmed_search_term TEXT := TRIM(p_search_term); -- Trim the search term here
BEGIN
    current_user_id := auth.uid();
    IF current_user_id IS NULL THEN
        RAISE EXCEPTION 'Only logged-in users can call this function';
    END IF;

    SELECT array_agg(r.name) INTO user_roles
    FROM public.user_roles ur
    JOIN public.roles r ON ur.role = r.id
    WHERE ur."user" = current_user_id;

    user_is_admin := COALESCE('admin' = ANY(user_roles), FALSE);

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
            ul.value AS user_like_status,
            like_counts.likes AS like_count,
            like_counts.dislikes AS dislike_count,
            uhs.snippet IS NOT NULL AS hidden
        FROM snippets s
        LEFT JOIN audio_files a ON s.audio_file = a.id
        LEFT JOIN user_star_snippets us ON us.snippet = s.id AND us."user" = current_user_id
        LEFT JOIN user_like_snippets ul ON ul.snippet = s.id AND ul."user" = current_user_id
        LEFT JOIN user_hide_snippets uhs ON uhs.snippet = s.id
        CROSS JOIN LATERAL (
            SELECT
                COUNT(*) FILTER (WHERE value = 1) AS likes,
                COUNT(*) FILTER (WHERE value = -1) AS dislikes
            FROM user_like_snippets uls
            WHERE uls.snippet = s.id
        ) like_counts
        WHERE s.status = 'Processed' AND (s.confidence_scores->>'overall')::INTEGER >= 95
        AND (
            -- If user is admin, show all snippets (including hidden ones)
            -- If user is not admin, only show non-hidden snippets
            user_is_admin OR
            NOT EXISTS (
                SELECT 1
                FROM user_hide_snippets uhs
                WHERE uhs.snippet = s.id
            )
        )
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
        AND (
            p_filter IS NULL OR
            NOT p_filter ? 'upvotedBy' OR
            (
                CASE
                    WHEN jsonb_array_length(p_filter->'upvotedBy') = 0 THEN TRUE
                    ELSE (
                        CASE
                            WHEN (
                                p_filter->'upvotedBy' ? 'by_me' AND
                                p_filter->'upvotedBy' ? 'by_others'
                            ) THEN
                                EXISTS (
                                    SELECT 1
                                    FROM label_upvotes lu
                                    WHERE lu.snippet_label IN (
                                        SELECT id FROM snippet_labels WHERE snippet = s.id
                                    )
                                )
                            WHEN p_filter->'upvotedBy' ? 'by_me' THEN
                                EXISTS (
                                    SELECT 1
                                    FROM label_upvotes lu
                                    WHERE lu.snippet_label IN (
                                        SELECT id FROM snippet_labels WHERE snippet = s.id
                                    )
                                    AND lu.upvoted_by = current_user_id
                                )
                            WHEN p_filter->'upvotedBy' ? 'by_others' THEN
                                EXISTS (
                                    SELECT 1
                                    FROM label_upvotes lu
                                    WHERE lu.snippet_label IN (
                                        SELECT id FROM snippet_labels WHERE snippet = s.id
                                    )
                                    AND lu.upvoted_by != current_user_id
                                )
                            ELSE FALSE
                        END
                    )
                END
            )
        )
        AND (
            trimmed_search_term = '' OR (
                ((s.title ->> 'english') || ' ' || (s.title ->> 'spanish')) &@ trimmed_search_term
                OR ((s.explanation ->> 'english') || ' ' || (s.explanation ->> 'spanish')) &@ trimmed_search_term
                OR ((s.summary ->> 'english') || ' ' || (s.summary ->> 'spanish')) &@ trimmed_search_term
                OR s.transcription &@ trimmed_search_term                 
                OR s.translation &@ trimmed_search_term
            )
        )
        ORDER BY 
            CASE
                WHEN p_order_by = 'upvotes' THEN s.upvote_count + s.like_count
                WHEN p_order_by = 'comments' THEN s.comment_count 
                WHEN p_order_by = 'activities' THEN EXTRACT(EPOCH FROM s.updated_at)
                WHEN p_order_by IS NULL OR p_order_by = 'latest' OR p_order_by = '' THEN EXTRACT(EPOCH FROM s.recorded_at)
                ELSE EXTRACT(EPOCH FROM s.recorded_at)
            END DESC,
            s.recorded_at DESC;
        
    SELECT COUNT(*) INTO total_count
    FROM filtered_snippets;

    SELECT jsonb_agg(fs.*) INTO result
    FROM (
        SELECT * FROM filtered_snippets
        LIMIT page_size
        OFFSET page * page_size
    ) fs;

    DROP TABLE filtered_snippets;

    total_pages := CEIL(total_count::FLOAT / page_size);

    RETURN jsonb_build_object(
        'num_of_snippets', total_count,
        'snippets', COALESCE(result, '[]'::jsonb),
        'current_page', page,
        'page_size', page_size,
        'total_pages', total_pages
    );
END;
$$ LANGUAGE plpgsql;
