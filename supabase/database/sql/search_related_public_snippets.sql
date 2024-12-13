CREATE OR REPLACE FUNCTION search_related_snippets_public(
    snippet_id uuid,
    p_language TEXT DEFAULT 'english',
    match_threshold float DEFAULT 0.7,
    match_count int DEFAULT 5
)
RETURNS jsonb
SECURITY DEFINER AS $$
DECLARE
    source_embedding vector(3072);
    result jsonb;
BEGIN
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
            jsonb_agg(l) as labels
        FROM snippet_embeddings se
        JOIN snippets s ON s.id = se.snippet
        JOIN audio_files a ON a.id = s.audio_file
        LEFT JOIN snippet_labels sl ON s.id = sl.snippet
        LEFT JOIN labels l ON sl.label = l.id
        WHERE
            se.snippet != snippet_id
            AND 1 - (se.embedding <=> source_embedding) > match_threshold
            AND se.status = 'Processed'
        GROUP BY 
            s.id,
            s.title,
            s.file_path,
            s.recorded_at,
            s.comment_count,
            s.start_time,
            a.radio_station_name,
            a.radio_station_code,
            a.location_state,
            summary,
            similarity
        ORDER BY similarity DESC
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
            'labels', ss.labels,
            'recorded_at', ss.recorded_at,
            'comment_count', ss.comment_count,
            'similarity', ss.similarity,
            'file_path', ss.file_path,
            'start_time', ss.start_time
        )
    ) INTO result
    FROM similar_snippets ss;

    RETURN COALESCE(result, '[]'::jsonb);
END;
$$ LANGUAGE plpgsql;
