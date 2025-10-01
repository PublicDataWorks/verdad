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

    WITH
    snippets_with_similarity AS (
        SELECT
            s.id,
            1 - (se.embedding <=> source_embedding) as similarity
        FROM snippet_embeddings se
        JOIN snippets s ON s.id = se.snippet
        WHERE
            se.snippet != snippet_id
            AND s.status = 'Processed'
    ),
    similar_snippets AS (
        SELECT *
        FROM snippets_with_similarity
        WHERE similarity > match_threshold
        ORDER BY similarity DESC
        LIMIT match_count
    ),
    label_summary AS (
        SELECT
            sl.snippet,
            COALESCE(
                jsonb_agg(
                    jsonb_build_object(
                        'text', l.text,
                        'text_spanish', l.text_spanish
                    )
                ),
                '[]'::jsonb
            ) AS labels
        FROM snippet_labels sl
        JOIN labels l ON l.id = sl.label
        WHERE sl.snippet IN (SELECT id FROM similar_snippets)
        GROUP BY sl.snippet
    ),
    final_snippets AS (
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
            ss.similarity,
            COALESCE(ls.labels, '[]'::jsonb) AS labels
        FROM similar_snippets ss
        JOIN snippets s ON s.id = ss.id
        JOIN audio_files a ON a.id = s.audio_file
        LEFT JOIN label_summary ls ON ss.id = ls.snippet
    )
    SELECT jsonb_agg(
        jsonb_build_object(
            'id', fs.id,
            'title', fs.title,
            'radio_station_name', fs.radio_station_name,
            'radio_station_code', fs.radio_station_code,
            'location_state', fs.location_state,
            'summary', fs.summary,
            'labels', fs.labels,
            'recorded_at', fs.recorded_at,
            'comment_count', fs.comment_count,
            'similarity', fs.similarity,
            'file_path', fs.file_path,
            'start_time', fs.start_time
        )
    ) INTO result
    FROM final_snippets fs;

    RETURN COALESCE(result, '[]'::jsonb);
END;
$$ LANGUAGE plpgsql
SET statement_timeout TO '30s';
