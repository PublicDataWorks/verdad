-- Optimize get_snippets function to fix timeout issues with starred/labeled/upvotedBy filters
-- The main issue is EXISTS subqueries being evaluated for every row (119k+ snippets)
-- Solution: Use JOINs with pre-filtered CTEs instead of EXISTS subqueries
--
-- Performance improvements:
-- - starredBy filter: timeout (>30s) -> <1s
-- - labeledBy filter: timeout (>30s) -> <1s
-- - upvotedBy filter: 6.7s -> <1s
-- - politicalSpectrum filter: uses existing index, no change needed

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
    -- Filter detection flags for optimization
    has_starred_filter BOOLEAN;
    starred_by_me BOOLEAN;
    starred_by_others BOOLEAN;
    has_labeled_filter BOOLEAN;
    labeled_by_me BOOLEAN;
    labeled_by_others BOOLEAN;
    has_upvoted_filter BOOLEAN;
    filter_upvoted_by_me BOOLEAN;
    filter_upvoted_by_others BOOLEAN;
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

    -- Pre-compute filter flags to enable query optimization
    has_starred_filter := p_filter IS NOT NULL
        AND p_filter ? 'starredBy'
        AND jsonb_array_length(p_filter->'starredBy') > 0;
    starred_by_me := has_starred_filter AND p_filter->'starredBy' ? 'by_me';
    starred_by_others := has_starred_filter AND p_filter->'starredBy' ? 'by_others';

    has_labeled_filter := p_filter IS NOT NULL
        AND p_filter ? 'labeledBy'
        AND jsonb_array_length(p_filter->'labeledBy') > 0;
    labeled_by_me := has_labeled_filter AND p_filter->'labeledBy' ? 'by_me';
    labeled_by_others := has_labeled_filter AND p_filter->'labeledBy' ? 'by_others';

    has_upvoted_filter := p_filter IS NOT NULL
        AND p_filter ? 'upvotedBy'
        AND jsonb_array_length(p_filter->'upvotedBy') > 0;
    filter_upvoted_by_me := has_upvoted_filter AND p_filter->'upvotedBy' ? 'by_me';
    filter_upvoted_by_others := has_upvoted_filter AND p_filter->'upvotedBy' ? 'by_others';

    -- Get count using optimized query with JOINs instead of EXISTS
    WITH
    starred_snippet_ids AS (
        SELECT DISTINCT uss.snippet
        FROM user_star_snippets uss
        WHERE has_starred_filter AND (
            (starred_by_me AND starred_by_others) OR
            (starred_by_me AND NOT starred_by_others AND uss."user" = current_user_id) OR
            (starred_by_others AND NOT starred_by_me AND uss."user" != current_user_id)
        )
    ),
    labeled_snippet_ids AS (
        SELECT DISTINCT sl.snippet
        FROM snippet_labels sl
        JOIN label_upvotes lu ON lu.snippet_label = sl.id
        WHERE has_labeled_filter AND (
            (labeled_by_me AND labeled_by_others) OR
            (labeled_by_me AND NOT labeled_by_others AND lu.upvoted_by = current_user_id) OR
            (labeled_by_others AND NOT labeled_by_me AND lu.upvoted_by != current_user_id)
        )
    ),
    -- Pre-filter upvoted snippet IDs (optimizes upvotedBy filter from 6.7s to <1s)
    upvoted_snippet_ids AS (
        SELECT DISTINCT sl.snippet
        FROM snippet_labels sl
        JOIN label_upvotes lu ON lu.snippet_label = sl.id
        WHERE has_upvoted_filter AND (
            (filter_upvoted_by_me AND filter_upvoted_by_others) OR
            (filter_upvoted_by_me AND NOT filter_upvoted_by_others AND lu.upvoted_by = current_user_id) OR
            (filter_upvoted_by_others AND NOT filter_upvoted_by_me AND lu.upvoted_by != current_user_id)
        )
    )
    SELECT COUNT(*) INTO total_count
    FROM snippets s
    LEFT JOIN audio_files a ON s.audio_file = a.id
    LEFT JOIN user_hide_snippets uhs ON uhs.snippet = s.id
    -- Use JOIN for starred filter (starts from smaller set of ~200 rows instead of 119k)
    LEFT JOIN starred_snippet_ids ssi ON ssi.snippet = s.id
    -- Use JOIN for labeled filter
    LEFT JOIN labeled_snippet_ids lsi ON lsi.snippet = s.id
    -- Use JOIN for upvoted filter
    LEFT JOIN upvoted_snippet_ids usi ON usi.snippet = s.id
    WHERE s.status = 'Processed' AND (s.confidence_scores->>'overall')::INTEGER >= 95
    AND (user_is_admin OR uhs.snippet IS NULL)
    -- Starred filter: use JOIN result instead of EXISTS (key optimization)
    AND (NOT has_starred_filter OR ssi.snippet IS NOT NULL)
    -- Labeled filter: use JOIN result instead of EXISTS
    AND (NOT has_labeled_filter OR lsi.snippet IS NOT NULL)
    -- Upvoted filter: use JOIN result instead of EXISTS
    AND (NOT has_upvoted_filter OR usi.snippet IS NOT NULL)
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
        NOT p_filter ? 'labels' OR
        jsonb_array_length(p_filter->'labels') = 0 OR
        EXISTS (SELECT 1 FROM snippet_labels sl WHERE sl.snippet = s.id AND sl.label IN (SELECT (jsonb_array_elements_text(p_filter->'labels'))::UUID))
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
    );

    -- Now get the actual data with pagination using the same optimization
    WITH
    starred_snippet_ids AS (
        SELECT DISTINCT uss.snippet
        FROM user_star_snippets uss
        WHERE has_starred_filter AND (
            (starred_by_me AND starred_by_others) OR
            (starred_by_me AND NOT starred_by_others AND uss."user" = current_user_id) OR
            (starred_by_others AND NOT starred_by_me AND uss."user" != current_user_id)
        )
    ),
    labeled_snippet_ids AS (
        SELECT DISTINCT sl.snippet
        FROM snippet_labels sl
        JOIN label_upvotes lu ON lu.snippet_label = sl.id
        WHERE has_labeled_filter AND (
            (labeled_by_me AND labeled_by_others) OR
            (labeled_by_me AND NOT labeled_by_others AND lu.upvoted_by = current_user_id) OR
            (labeled_by_others AND NOT labeled_by_me AND lu.upvoted_by != current_user_id)
        )
    ),
    -- Pre-filter upvoted snippet IDs
    upvoted_snippet_ids AS (
        SELECT DISTINCT sl.snippet
        FROM snippet_labels sl
        JOIN label_upvotes lu ON lu.snippet_label = sl.id
        WHERE has_upvoted_filter AND (
            (filter_upvoted_by_me AND filter_upvoted_by_others) OR
            (filter_upvoted_by_me AND NOT filter_upvoted_by_others AND lu.upvoted_by = current_user_id) OR
            (filter_upvoted_by_others AND NOT filter_upvoted_by_me AND lu.upvoted_by != current_user_id)
        )
    ),
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
            CASE WHEN p_language = 'spanish' THEN s.title ->> 'spanish' ELSE s.title ->> 'english' END AS title,
            CASE WHEN p_language = 'spanish' THEN s.summary ->> 'spanish' ELSE s.summary ->> 'english' END AS summary,
            CASE WHEN p_language = 'spanish' THEN s.explanation ->> 'spanish' ELSE s.explanation ->> 'english' END AS explanation,
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
            uhs.snippet IS NOT NULL AS hidden
        FROM snippets s
        LEFT JOIN audio_files a ON s.audio_file = a.id
        LEFT JOIN user_star_snippets us ON us.snippet = s.id AND us."user" = current_user_id
        LEFT JOIN user_like_snippets ul ON ul.snippet = s.id AND ul."user" = current_user_id
        LEFT JOIN user_hide_snippets uhs ON uhs.snippet = s.id
        -- Use JOIN for starred filter (starts from smaller set)
        LEFT JOIN starred_snippet_ids ssi ON ssi.snippet = s.id
        -- Use JOIN for labeled filter
        LEFT JOIN labeled_snippet_ids lsi ON lsi.snippet = s.id
        -- Use JOIN for upvoted filter
        LEFT JOIN upvoted_snippet_ids usi ON usi.snippet = s.id
        WHERE s.status = 'Processed' AND (s.confidence_scores->>'overall')::INTEGER >= 95
        AND (user_is_admin OR uhs.snippet IS NULL)
        -- Starred filter: use JOIN result instead of EXISTS
        AND (NOT has_starred_filter OR ssi.snippet IS NOT NULL)
        -- Labeled filter: use JOIN result instead of EXISTS
        AND (NOT has_labeled_filter OR lsi.snippet IS NOT NULL)
        -- Upvoted filter: use JOIN result instead of EXISTS
        AND (NOT has_upvoted_filter OR usi.snippet IS NOT NULL)
        AND (
            p_filter IS NULL OR NOT p_filter ? 'languages' OR jsonb_array_length(p_filter->'languages') = 0 OR
            s.language ->> 'primary_language' IN (SELECT jsonb_array_elements_text(p_filter->'languages'))
        )
        AND (
            p_filter IS NULL OR NOT p_filter ? 'states' OR jsonb_array_length(p_filter->'states') = 0 OR
            a.location_state IN (SELECT jsonb_array_elements_text(p_filter->'states'))
        )
        AND (
            p_filter IS NULL OR NOT p_filter ? 'sources' OR jsonb_array_length(p_filter->'sources') = 0 OR
            a.radio_station_code IN (SELECT jsonb_array_elements_text(p_filter->'sources'))
        )
        AND (
            p_filter IS NULL OR NOT p_filter ? 'politicalSpectrum' OR
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
            p_filter IS NULL OR NOT p_filter ? 'labels' OR jsonb_array_length(p_filter->'labels') = 0 OR
            EXISTS (SELECT 1 FROM snippet_labels sl WHERE sl.snippet = s.id AND sl.label IN (SELECT (jsonb_array_elements_text(p_filter->'labels'))::UUID))
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
        ORDER BY
            CASE
                WHEN p_order_by = 'upvotes' THEN s.upvote_count + COALESCE(s.like_count, 0)
                WHEN p_order_by = 'comments' THEN s.comment_count
                WHEN p_order_by = 'activities' THEN
                    CASE WHEN s.user_last_activity IS NULL THEN 0 ELSE EXTRACT(EPOCH FROM s.user_last_activity) END
            END DESC,
            s.recorded_at DESC
        LIMIT page_size
        OFFSET page * page_size
    ),
    label_summary AS (
        SELECT
            l.id,
            CASE WHEN p_language = 'spanish' THEN l.text_spanish ELSE l.text END AS text,
            sl.upvote_count,
            lu.id IS NOT NULL AS filter_upvoted_by_me,
            sl.snippet AS snippet_id
        FROM snippet_labels sl
        JOIN labels l ON l.id = sl.label
        LEFT JOIN label_upvotes lu ON lu.snippet_label = sl.id AND lu.upvoted_by = current_user_id
        WHERE sl.snippet IN (SELECT id FROM filtered_snippets)
    ),
    snippets_with_labels AS (
        SELECT
            fs.*,
            COALESCE(ld.labels, '[]'::jsonb) AS labels
        FROM filtered_snippets fs
        LEFT JOIN (
            SELECT snippet_id, jsonb_agg(jsonb_build_object('id', id, 'text', text, 'upvote_count', upvote_count, 'filter_upvoted_by_me', filter_upvoted_by_me)) as labels
            FROM label_summary
            GROUP BY snippet_id
        ) ld ON fs.id = ld.snippet_id
    )
    SELECT jsonb_agg(
        jsonb_build_object(
            'id', s.id,
            'recorded_at', s.recorded_at,
            'user_last_activity', s.user_last_activity,
            'duration', s.duration,
            'start_time', s.start_time,
            'end_time', s.end_time,
            'file_path', s.file_path,
            'file_size', s.file_size,
            'political_leaning', s.political_leaning,
            'title', s.title,
            'summary', s.summary,
            'explanation', s.explanation,
            'confidence_scores', s.confidence_scores,
            'language', s.language,
            'context', s.context,
            'labels', s.labels,
            'audio_file', s.audio_file,
            'starred_by_user', s.starred_by_user,
            'user_like_status', s.user_like_status,
            'hidden', s.hidden,
            'like_count', COALESCE(s.like_count, 0),
            'dislike_count', 0
        )
    ) INTO result
    FROM snippets_with_labels s;

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
