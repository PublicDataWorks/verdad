-- find_duplicate_kb_entries: High-threshold similarity search for deduplication.
-- Searches across entries that have embeddings. Superseded and deactivated entries
-- are excluded because their embeddings are deleted on status change.
CREATE OR REPLACE FUNCTION find_duplicate_kb_entries(
    query_embedding vector(3072),
    similarity_threshold FLOAT DEFAULT 0.92,
    max_results INT DEFAULT 5
)
RETURNS jsonb
SECURITY DEFINER AS $$
DECLARE
    query_sub_embedding vector(512);
    result jsonb;
BEGIN
    query_sub_embedding := sub_vector(query_embedding, 512)::vector(512);

    WITH candidates AS (
        SELECT
            ke.id AS entry_id,
            kee.embedding
        FROM kb_entry_embeddings kee
        JOIN kb_entries ke ON ke.id = kee.kb_entry
        WHERE kee.status = 'Processed'
            -- Search across ALL statuses for deduplication
        ORDER BY
            sub_vector(kee.embedding, 512)::vector(512) <#> query_sub_embedding ASC
        LIMIT max_results * 4
    ),
    ranked AS (
        SELECT
            c.entry_id,
            -(c.embedding <#> query_embedding) AS similarity
        FROM candidates c
        WHERE -(c.embedding <#> query_embedding) > similarity_threshold
        ORDER BY c.embedding <#> query_embedding ASC
        LIMIT max_results
    ),
    final_entries AS (
        SELECT
            jsonb_build_object(
                'id', ke.id,
                'fact', ke.fact,
                'related_claim', ke.related_claim,
                'confidence_score', ke.confidence_score,
                'status', ke.status::TEXT,
                'version', ke.version,
                'similarity', r.similarity
            ) AS entry
        FROM ranked r
        JOIN kb_entries ke ON ke.id = r.entry_id
        ORDER BY r.similarity DESC
    )
    SELECT jsonb_agg(fe.entry)
    INTO result
    FROM final_entries fe;

    RETURN COALESCE(result, '[]'::jsonb);
END;
$$ LANGUAGE plpgsql;
