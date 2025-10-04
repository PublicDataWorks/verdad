CREATE OR REPLACE FUNCTION search_related_snippets_public(
    snippet_id uuid,
    p_language TEXT DEFAULT 'english',
    match_threshold FLOAT DEFAULT 0.7,
    match_count INT DEFAULT 5,
    candidate_multiplier INT DEFAULT 8
)
RETURNS jsonb
SECURITY DEFINER AS $$
DECLARE
    source_embedding vector(3072);
    source_sub_embedding vector(512);
    result jsonb;
BEGIN
    -- Get the source snippet's embedding
    SELECT embedding, sub_vector(embedding, 512)::vector(512)
    INTO source_embedding, source_sub_embedding
    FROM snippet_embeddings
    WHERE snippet = snippet_id;

    -- If no embedding found, return empty array
    IF source_embedding IS NULL THEN
        RETURN '[]'::jsonb;
    END IF;

    WITH
    sub_similar_snippets AS (
        SELECT
            s.*,
            se.embedding
        FROM snippet_embeddings se
        JOIN snippets s ON s.id = se.snippet
        WHERE
            se.snippet != snippet_id
            AND s.status = 'Processed'
        ORDER BY
            sub_vector(embedding, 512)::vector(512) <#> source_sub_embedding ASC
        LIMIT match_count * candidate_multiplier
    ),
    similar_snippets AS (
        SELECT *
        FROM sub_similar_snippets
        WHERE -(embedding <#> source_embedding) > match_threshold -- Embedding is normalized so we can use inner product as similarity
        ORDER BY embedding <#> source_embedding ASC
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
            CASE
                WHEN p_language = 'spanish' THEN s.summary ->> 'spanish'
                ELSE s.summary ->> 'english'
            END AS summary,
            a.radio_station_name,
            a.radio_station_code,
            a.location_state,
            COALESCE(ls.labels, '[]'::jsonb) AS labels
        FROM similar_snippets s
        JOIN audio_files a ON a.id = s.audio_file
        LEFT JOIN label_summary ls ON ls.snippet = s.id
    )
    SELECT jsonb_agg(fs)
    INTO result
    FROM final_snippets fs;

    RETURN COALESCE(result, '[]'::jsonb);
END;
$$ LANGUAGE plpgsql;
