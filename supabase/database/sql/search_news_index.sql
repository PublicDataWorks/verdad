-- search_news_index: two-stage sub-vector search over the dated news ledger (news_index).
--
-- This repo keeps the function in two places on purpose: the authoritative copy ships in
-- supabase/migrations/20260918000000_news_index.sql (which also creates the tables), and this loose file is
-- the hand-apply copy kept alongside the other search_* functions. Change both together.

-- search_news_index: two-stage sub-vector search, same pattern as search_kb_entries.
-- Adding a parameter creates a new overload under CREATE OR REPLACE, which would make the RPC call
-- ambiguous, so the previous signature is dropped first.
DROP FUNCTION IF EXISTS search_news_index(vector(3072), FLOAT, INT, INT, TIMESTAMPTZ, TIMESTAMPTZ);

CREATE OR REPLACE FUNCTION search_news_index(
    query_embedding vector(3072),
    match_threshold FLOAT DEFAULT 0.5,
    match_count INT DEFAULT 5,
    candidate_multiplier INT DEFAULT 8,
    published_after TIMESTAMPTZ DEFAULT NULL,
    published_before TIMESTAMPTZ DEFAULT NULL
)
RETURNS jsonb
SECURITY DEFINER AS $$
DECLARE
    query_sub_embedding vector(512);
    result jsonb;
BEGIN
    query_sub_embedding := sub_vector(query_embedding, 512)::vector(512);

    WITH
    -- Stage 1: Approximate search using the sub-vector HNSW index
    candidates AS (
        SELECT
            ni.id AS item_id,
            nie.embedding
        FROM public.news_index_embeddings nie
        JOIN public.news_index ni ON ni.id = nie.news_index
        WHERE
            nie.status = 'Processed'
            AND (published_after IS NULL OR ni.published_at >= published_after)
            AND (published_before IS NULL OR ni.published_at <= published_before)
        ORDER BY
            sub_vector(nie.embedding, 512)::vector(512) <#> query_sub_embedding ASC
        LIMIT match_count * candidate_multiplier
    ),
    -- Stage 2: Re-rank using full 3072-dim inner product
    ranked AS (
        SELECT
            c.item_id,
            -(c.embedding <#> query_embedding) AS similarity
        FROM candidates c
        WHERE -(c.embedding <#> query_embedding) > match_threshold
        ORDER BY c.embedding <#> query_embedding ASC
        LIMIT match_count
    ),
    final_items AS (
        SELECT
            jsonb_build_object(
                'id', ni.id,
                'outlet', ni.outlet,
                'url', ni.url,
                'title', ni.title,
                'summary', ni.summary,
                'published_at', to_char(ni.published_at AT TIME ZONE 'UTC', 'YYYY-MM-DD'),
                'credibility_tier', ni.credibility_tier,
                'similarity', r.similarity
            ) AS item
        FROM ranked r
        JOIN public.news_index ni ON ni.id = r.item_id
        ORDER BY r.similarity DESC
    )
    SELECT jsonb_agg(fi.item)
    INTO result
    FROM final_items fi;

    RETURN COALESCE(result, '[]'::jsonb);
END;
$$ LANGUAGE plpgsql;
