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
    trimmed_search_term TEXT := TRIM(p_search_term);
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

    -- First, get the total count separately to avoid COUNT(*) OVER() overhead
    SELECT COUNT(*) INTO total_count
    FROM snippets s
    LEFT JOIN audio_files a ON s.audio_file = a.id
    LEFT JOIN user_hide_snippets uhs ON uhs.snippet = s.id
    WHERE s.status = 'Processed' AND (s.confidence_scores->>'overall')::INTEGER >= 95
    AND (user_is_admin OR uhs.snippet IS NULL)
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
        -- Optimized full-text search: use individual indexed columns instead of concatenation
        -- This allows PostgreSQL to use PGroonga indexes on each column
        trimmed_search_term = '' OR (
            (s.title ->> 'english') &@ trimmed_search_term
            OR (s.title ->> 'spanish') &@ trimmed_search_term
            OR (s.explanation ->> 'english') &@ trimmed_search_term
            OR (s.explanation ->> 'spanish') &@ trimmed_search_term
            OR (s.summary ->> 'english') &@ trimmed_search_term
            OR (s.summary ->> 'spanish') &@ trimmed_search_term
            OR s.transcription &@ trimmed_search_term
            OR s.translation &@ trimmed_search_term
        )
    );

    -- Now get the paginated results without COUNT(*) OVER()
    WITH
    filtered_snippets AS (
        SELECT
            s.id,
            s.recorded_at,
            s.user_last_activity,
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
            s.upvote_count,
            s.comment_count,
            s.like_count,
            jsonb_build_object(
                'id', a.id,
                'radio_station_name', a.radio_station_name,
                'radio_station_code', a.radio_station_code,
                'location_state', a.location_state,
                'location_city', a.location_city
            ) AS audio_file,
            us.id IS NOT NULL AS starred_by_user,
            ul.value AS user_like_status,
            uhs.snippet IS NOT NULL AS hidden,
            0 AS dislike_count
        FROM snippets s
        LEFT JOIN audio_files a ON s.audio_file = a.id
        LEFT JOIN user_star_snippets us ON us.snippet = s.id AND us."user" = current_user_id
        LEFT JOIN user_like_snippets ul ON ul.snippet = s.id AND ul."user" = current_user_id
        LEFT JOIN user_hide_snippets uhs ON uhs.snippet = s.id
        WHERE s.status = 'Processed' AND (s.confidence_scores->>'overall')::INTEGER >= 95
        AND (user_is_admin OR uhs.snippet IS NULL)
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
                (s.title ->> 'english') &@ trimmed_search_term
                OR (s.title ->> 'spanish') &@ trimmed_search_term
                OR (s.explanation ->> 'english') &@ trimmed_search_term
                OR (s.explanation ->> 'spanish') &@ trimmed_search_term
                OR (s.summary ->> 'english') &@ trimmed_search_term
                OR (s.summary ->> 'spanish') &@ trimmed_search_term
                OR s.transcription &@ trimmed_search_term
                OR s.translation &@ trimmed_search_term
            )
        )
    ),
    paginated_snippets AS (
        SELECT fs.*
        FROM filtered_snippets fs
        ORDER BY
            CASE
                WHEN p_order_by = 'upvotes' THEN fs.upvote_count + fs.like_count
                WHEN p_order_by = 'comments' THEN fs.comment_count
                WHEN p_order_by = 'activities' THEN
                    CASE
                        WHEN fs.user_last_activity IS NULL THEN 0
                        ELSE EXTRACT(EPOCH FROM fs.user_last_activity)
                    END
            END DESC,
            fs.recorded_at DESC
        LIMIT page_size
        OFFSET page * page_size
    ),
    label_summary AS (
        SELECT
            l.id,
            CASE
                WHEN p_language = 'spanish' THEN l.text_spanish
                ELSE l.text
            END AS text,
            sl.upvote_count,
            lu.id IS NOT NULL AS upvoted_by_me,
            sl.snippet AS snippet_id
        FROM snippet_labels sl
        JOIN labels l ON l.id = sl.label
        LEFT JOIN label_upvotes lu ON lu.snippet_label = sl.id AND lu.upvoted_by = current_user_id
        WHERE sl.snippet IN (SELECT id FROM paginated_snippets)
    ),
    paginated_snippets_with_labels AS (
        SELECT
            ps.*,
            COALESCE(ld.labels, '[]'::jsonb) AS labels
        FROM paginated_snippets ps
        LEFT JOIN (
            SELECT
                snippet_id,
                jsonb_agg(
                    jsonb_build_object(
                        'id', id,
                        'text', text,
                        'upvote_count', upvote_count,
                        'upvoted_by_me', upvoted_by_me
                    )
                ) as labels
            FROM label_summary
            GROUP BY snippet_id
        ) ld ON ps.id = ld.snippet_id
        ORDER BY
            CASE
                WHEN p_order_by = 'upvotes' THEN ps.upvote_count + ps.like_count
                WHEN p_order_by = 'comments' THEN ps.comment_count
                WHEN p_order_by = 'activities' THEN
                    CASE
                        WHEN ps.user_last_activity IS NULL THEN 0
                        ELSE EXTRACT(EPOCH FROM ps.user_last_activity)
                    END
            END DESC,
            ps.recorded_at DESC
    )
    SELECT
        jsonb_agg(
            jsonb_build_object(
                'id', ps.id,
                'recorded_at', ps.recorded_at,
                'user_last_activity', ps.user_last_activity,
                'duration', ps.duration,
                'start_time', ps.start_time,
                'end_time', ps.end_time,
                'file_path', ps.file_path,
                'file_size', ps.file_size,
                'political_leaning', ps.political_leaning,
                'title', ps.title,
                'summary', ps.summary,
                'explanation', ps.explanation,
                'confidence_scores', ps.confidence_scores,
                'language', ps.language,
                'context', ps.context,
                'labels', ps.labels,
                'audio_file', ps.audio_file,
                'starred_by_user', ps.starred_by_user,
                'user_like_status', ps.user_like_status,
                'hidden', ps.hidden,
                'like_count', ps.like_count,
                'dislike_count', ps.dislike_count
            )
        )
    INTO result
    FROM paginated_snippets_with_labels ps;

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
