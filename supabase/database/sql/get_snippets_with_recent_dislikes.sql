DROP FUNCTION IF EXISTS get_snippets_with_recent_dislikes;

CREATE OR REPLACE FUNCTION get_snippets_with_recent_dislikes(
    p_since_date TIMESTAMPTZ DEFAULT NULL,
    p_exclude_validated BOOLEAN DEFAULT TRUE,
    p_limit INTEGER DEFAULT NULL
) RETURNS JSONB LANGUAGE plpgsql AS $$
DECLARE
    result JSONB;
BEGIN
    WITH dislike_counts AS (
        SELECT
            uls.snippet,
            COUNT(*) AS dislike_count
        FROM user_like_snippets uls
        WHERE uls.value = -1
          AND (p_since_date IS NULL OR uls.created_at >= p_since_date)
        GROUP BY uls.snippet
    ),
    filtered_snippets AS (
        SELECT dc.snippet, dc.dislike_count
        FROM dislike_counts dc
        WHERE NOT p_exclude_validated
            OR NOT EXISTS (
                SELECT 1
                FROM snippet_feedback_validation_results sfvr
                WHERE sfvr.snippet = dc.snippet
            )
    ),
    limited_snippets AS (
        SELECT s.*, fs.dislike_count
        FROM filtered_snippets fs
        JOIN snippets s ON s.id = fs.snippet
        ORDER BY fs.dislike_count DESC, s.recorded_at DESC
        LIMIT p_limit
    ),
    snippet_labels_agg AS (
        SELECT
            sl.snippet,
            jsonb_agg(
                jsonb_build_object(
                    'label', jsonb_build_object(
                        'text', l.text,
                        'text_spanish', l.text_spanish,
                        'is_ai_suggested', l.is_ai_suggested
                    ),
                    'created_at', sl.created_at
                )
            ) AS labels
        FROM snippet_labels sl
        JOIN labels l ON l.id = sl.label
        WHERE sl.snippet IN (SELECT id FROM limited_snippets)
          AND sl.applied_by IS NOT NULL
        GROUP BY sl.snippet
    )
    SELECT COALESCE(
        jsonb_agg(
            to_jsonb(ls) || jsonb_build_object(
                'audio_file', jsonb_build_object(
                    'radio_station_name', af.radio_station_name,
                    'radio_station_code', af.radio_station_code,
                    'location_state', af.location_state,
                    'location_city', af.location_city
                ),
                'labels', COALESCE(sla.labels, '[]'::jsonb)
            )
            ORDER BY ls.dislike_count DESC, ls.recorded_at DESC
        ),
        '[]'::jsonb
    )
    INTO result
    FROM limited_snippets ls
    LEFT JOIN audio_files af ON af.id = ls.audio_file
    LEFT JOIN snippet_labels_agg sla ON sla.snippet = ls.id;

    RETURN result;
END;
$$;
