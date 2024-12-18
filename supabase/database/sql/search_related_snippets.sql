CREATE OR REPLACE FUNCTION search_related_snippets(
    snippet_id uuid,
    p_language TEXT DEFAULT 'english',
    match_threshold float DEFAULT 0.7,
    match_count int DEFAULT 5
)
RETURNS jsonb
SECURITY DEFINER AS $$
DECLARE
    current_user_id UUID;
    source_embedding vector(3072);
    result jsonb;
BEGIN
    -- Check if the user is authenticated
    current_user_id := auth.uid();
    IF current_user_id IS NULL THEN
        RAISE EXCEPTION 'Only logged-in users can call this function';
    END IF;

    -- Get the source snippet's embedding
    SELECT embedding INTO source_embedding
    FROM snippet_embeddings
    WHERE snippet = snippet_id;

    -- If no embedding found, return empty array
    IF source_embedding IS NULL THEN
        RETURN '[]'::jsonb;
    END IF;

    WITH similar_snippets AS (
        SELECT
            s.id,
            s.title,
            s.file_path,
            s.recorded_at,
            s.comment_count,
            s.start_time,
            a.radio_station_name,
            a.radio_station_code,
            a.location_state,
            CASE
                WHEN p_language = 'spanish' THEN s.summary ->> 'spanish'
                ELSE s.summary ->> 'english'
            END AS summary,
            1 - (se.embedding <=> source_embedding) as similarity,
            CASE
                WHEN us.id IS NOT NULL THEN true
                ELSE false
            END AS starred_by_user
        FROM snippet_embeddings se
        JOIN snippets s ON s.id = se.snippet
        JOIN audio_files a ON a.id = s.audio_file
        LEFT JOIN user_star_snippets us ON us.snippet = s.id AND us."user" = current_user_id
        WHERE
            se.snippet != snippet_id
            AND 1 - (se.embedding <=> source_embedding) > match_threshold
            AND se.status = 'Processed'
        ORDER BY se.embedding <=> source_embedding
        LIMIT match_count
    )
    SELECT jsonb_agg(
        jsonb_build_object(
            'id', ss.id,
            'title', ss.title,
            'radio_station_name', ss.radio_station_name,
            'radio_station_code', ss.radio_station_code,
            'location_state', ss.location_state,
            'summary', ss.summary,
            'labels', get_snippet_labels(ss.id, p_language) -> 'labels',
            'recorded_at', ss.recorded_at,
            'comment_count', ss.comment_count,
            'similarity', ss.similarity,
            'starred_by_user', ss.starred_by_user,
            'file_path', ss.file_path,
            'start_time', ss.start_time
        )
    ) INTO result
    FROM similar_snippets ss;

    RETURN COALESCE(result, '[]'::jsonb);
END;
$$ LANGUAGE plpgsql;
