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
        SELECT
            s.id,
            s.recorded_at,
            s.transcription,
            s.translation,
            s.title,
            s.summary,
            s.explanation,
            s.disinformation_categories,
            s.confidence_scores,
            s.audio_file,
            fs.dislike_count
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
                    'text', l.text,
                    'created_at', sl.created_at,
                    'upvote_count', sl.upvote_count
                )
            ) AS labels
        FROM snippet_labels sl
        JOIN labels l ON l.id = sl.label
        WHERE sl.snippet IN (SELECT id FROM limited_snippets)
          AND sl.applied_by IS NOT NULL
        GROUP BY sl.snippet
    ),
    comments_agg AS (
        SELECT
            c.room_id AS snippet,
            jsonb_agg(
                jsonb_build_object(
                    'body', c.body,
                    'comment_at', c.comment_at
                )
                ORDER BY c.comment_at ASC
            ) AS comments
        FROM comments c
        WHERE c.room_id IN (SELECT id FROM limited_snippets)
        GROUP BY c.room_id
    )
    SELECT COALESCE(
        jsonb_agg(
            to_jsonb(ls) || jsonb_build_object(
                'audio_file', jsonb_build_object(
                    'radio_station_name', af.radio_station_name,
                    'radio_station_code', af.radio_station_code,
                    'location_state', af.location_state
                ),
                'labels', COALESCE(sla.labels, '[]'::jsonb),
                'comments', COALESCE(ca.comments, '[]'::jsonb)
            )
            ORDER BY ls.dislike_count DESC, ls.recorded_at DESC
        ),
        '[]'::jsonb
    )
    INTO result
    FROM limited_snippets ls
    LEFT JOIN audio_files af ON af.id = ls.audio_file
    LEFT JOIN snippet_labels_agg sla ON sla.snippet = ls.id
    LEFT JOIN comments_agg ca ON ca.snippet = ls.id;

    RETURN result;
END;
$$;
