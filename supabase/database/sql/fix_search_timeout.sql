-- Fix for search timeout issues
-- The search_related_snippets function was doing sequential scans on 121K+ embeddings
-- This rewrites it to use a two-stage search pattern like search_related_snippets_public:
-- 1. First stage: Use sub_vector(512) with the existing HNSW index to get candidates fast
-- 2. Second stage: Re-rank candidates using full 3072-dim embedding similarity

-- Drop the old function signature first
DROP FUNCTION IF EXISTS search_related_snippets(uuid, text, double precision, integer);

CREATE OR REPLACE FUNCTION search_related_snippets(
    p_snippet_id uuid,
    p_language TEXT DEFAULT 'english',
    match_threshold float DEFAULT 0.7,
    match_count int DEFAULT 5,
    candidate_multiplier int DEFAULT 8  -- How many candidates to fetch in first pass
)
RETURNS jsonb
SECURITY DEFINER AS $$
DECLARE
    source_embedding vector(3072);
    source_sub_embedding vector(512);
    result jsonb;
BEGIN
    -- Get the source snippet's embedding and sub-vector
    SELECT embedding, sub_vector(embedding, 512)::vector(512)
    INTO source_embedding, source_sub_embedding
    FROM snippet_embeddings
    WHERE snippet = p_snippet_id;

    -- If no embedding found, return empty array
    IF source_embedding IS NULL THEN
        RETURN '[]'::jsonb;
    END IF;

    -- Two-stage search:
    -- Stage 1: Fast approximate search using sub-vector (uses HNSW index)
    -- Stage 2: Re-rank using full embedding and apply threshold
    WITH sub_similar AS (
        SELECT
            se.snippet as candidate_snippet_id,
            se.embedding
        FROM snippet_embeddings se
        WHERE se.snippet != p_snippet_id
        ORDER BY sub_vector(se.embedding, 512)::vector(512) <#> source_sub_embedding ASC
        LIMIT match_count * candidate_multiplier
    ),
    full_similar AS (
        SELECT
            candidate_snippet_id,
            1 - (embedding <=> source_embedding) as similarity
        FROM sub_similar
        WHERE 1 - (embedding <=> source_embedding) > match_threshold
        ORDER BY embedding <=> source_embedding ASC
        LIMIT match_count
    ),
    similar_snippets AS (
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
            fs.similarity,
            jsonb_agg(l) as labels
        FROM full_similar fs
        JOIN snippets s ON s.id = fs.candidate_snippet_id
        JOIN audio_files a ON a.id = s.audio_file
        LEFT JOIN snippet_labels sl ON s.id = sl.snippet
        LEFT JOIN labels l ON sl.label = l.id
        WHERE s.status = 'Processed'
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
            fs.similarity
        ORDER BY fs.similarity DESC
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
