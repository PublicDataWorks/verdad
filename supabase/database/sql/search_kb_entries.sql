-- search_kb_entries: Two-stage sub-vector search for knowledge base entries.
-- Same pattern as search_related_snippets_public.sql.
-- Stage 1: Approximate search using 512-dim HNSW index
-- Stage 2: Re-rank with full 3072-dim inner product
CREATE OR REPLACE FUNCTION search_kb_entries(
    query_embedding vector(3072),
    match_threshold FLOAT DEFAULT 0.3,
    match_count INT DEFAULT 10,
    candidate_multiplier INT DEFAULT 8,
    filter_categories TEXT[] DEFAULT NULL,
    reference_date TIMESTAMPTZ DEFAULT now()
)
RETURNS jsonb
SECURITY DEFINER AS $$
DECLARE
    query_sub_embedding vector(512);
    result jsonb;
BEGIN
    -- Compute the sub-vector for the first-pass HNSW search
    query_sub_embedding := sub_vector(query_embedding, 512)::vector(512);

    WITH
    -- Stage 1: Approximate search using sub-vector HNSW index
    candidates AS (
        SELECT
            ke.id AS entry_id,
            kee.embedding
        FROM kb_entry_embeddings kee
        JOIN kb_entries ke ON ke.id = kee.kb_entry
        WHERE
            ke.status = 'active'
            AND kee.status = 'Processed'
            -- Optional category filter
            AND (filter_categories IS NULL
                 OR ke.disinformation_categories && filter_categories)
            -- Temporal relevance: exclude entries outside their valid range
            AND (ke.valid_from IS NULL OR ke.valid_from <= reference_date)
            AND (ke.valid_until IS NULL OR ke.valid_until >= reference_date)
        ORDER BY
            sub_vector(kee.embedding, 512)::vector(512) <#> query_sub_embedding ASC
        LIMIT match_count * candidate_multiplier
    ),
    -- Stage 2: Re-rank using full 3072-dim inner product
    ranked AS (
        SELECT
            c.entry_id,
            -(c.embedding <#> query_embedding) AS similarity
        FROM candidates c
        WHERE -(c.embedding <#> query_embedding) > match_threshold
        ORDER BY c.embedding <#> query_embedding ASC
        LIMIT match_count
    ),
    -- Aggregate sources per entry
    source_agg AS (
        SELECT
            ks.kb_entry,
            jsonb_agg(
                jsonb_build_object(
                    'url', ks.url,
                    'source_name', ks.source_name,
                    'source_type', ks.source_type,
                    'title', ks.title,
                    'relevant_excerpt', ks.relevant_excerpt,
                    'publication_date', ks.publication_date,
                    'relevance_to_claim', ks.relevance_to_claim
                )
            ) AS sources
        FROM kb_entry_sources ks
        WHERE ks.kb_entry IN (SELECT entry_id FROM ranked)
        GROUP BY ks.kb_entry
    ),
    -- Build final result
    final_entries AS (
        SELECT
            jsonb_build_object(
                'id', ke.id,
                'fact', ke.fact,
                'related_claim', ke.related_claim,
                'confidence_score', ke.confidence_score,
                'valid_from', ke.valid_from,
                'valid_until', ke.valid_until,
                'is_time_sensitive', ke.is_time_sensitive,
                'disinformation_categories', ke.disinformation_categories,
                'keywords', ke.keywords,
                'version', ke.version,
                'created_at', ke.created_at,
                'similarity', r.similarity,
                'sources', COALESCE(sa.sources, '[]'::jsonb)
            ) AS entry
        FROM ranked r
        JOIN kb_entries ke ON ke.id = r.entry_id
        LEFT JOIN source_agg sa ON sa.kb_entry = ke.id
        ORDER BY r.similarity DESC
    )
    SELECT jsonb_agg(fe.entry)
    INTO result
    FROM final_entries fe;

    RETURN COALESCE(result, '[]'::jsonb);
END;
$$ LANGUAGE plpgsql;
