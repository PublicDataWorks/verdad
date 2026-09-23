-- news_index: a dated ledger of wire-service, public-broadcaster and IFCN fact-checker headlines.
--
-- Why it exists: Stage 3 runs on a model whose knowledge cutoff predates the events it is asked about, and
-- open web search often returns nothing on-topic, so true post-cutoff events get labelled "fabricated". This
-- table is a curated, dated evidence source that the pipeline itself never writes to (only the news ledger
-- poller does), so it cannot self-poison the way kb_entries can.
--
-- NOT YET APPLIED to production. Apply in the Supabase SQL editor, then record the version in
-- supabase/migrations/applied_versions.txt.

CREATE TABLE IF NOT EXISTS public.news_index (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    outlet TEXT NOT NULL,
    feed_url TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    summary TEXT,
    published_at TIMESTAMPTZ NOT NULL,
    language TEXT,

    -- 1 = wire service / public broadcaster / IFCN fact-checker, 2 = major outlet.
    credibility_tier SMALLINT NOT NULL DEFAULT 2,

    fetched_at TIMESTAMPTZ DEFAULT now(),
    content_hash TEXT
);

CREATE INDEX IF NOT EXISTS news_index_published_at_idx ON public.news_index (published_at DESC);
CREATE INDEX IF NOT EXISTS news_index_outlet_idx ON public.news_index (outlet);

CREATE TABLE IF NOT EXISTS public.news_index_embeddings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    news_index UUID NOT NULL UNIQUE REFERENCES public.news_index(id) ON DELETE CASCADE,
    embedding vector(3072),
    status TEXT NOT NULL DEFAULT 'New',
    model_name TEXT,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Mirrors snippet_embeddings_sub_vector_idx.sql: the first-pass HNSW index is built on the 512-dim
-- sub-vector, because pgvector cannot index 3072 dimensions directly.
CREATE INDEX IF NOT EXISTS news_index_embeddings_sub_vector_idx ON public.news_index_embeddings
    USING hnsw ((sub_vector(embedding, 512)::vector(512)) vector_ip_ops)
    WITH (m = 32, ef_construction = 400);

-- RLS + grants, following create_knowledge_base.sql.
ALTER TABLE public.news_index ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.news_index_embeddings ENABLE ROW LEVEL SECURITY;

GRANT ALL ON TABLE public.news_index TO service_role;
GRANT ALL ON TABLE public.news_index_embeddings TO service_role;
GRANT SELECT ON TABLE public.news_index TO authenticated;

DO $$ BEGIN
    CREATE POLICY "Enable read access for authenticated users"
        ON public.news_index FOR SELECT TO authenticated USING (true);
EXCEPTION WHEN duplicate_object THEN null; END $$;

DO $$ BEGIN
    CREATE POLICY "Enable full access for service role"
        ON public.news_index FOR ALL TO service_role USING (true);
EXCEPTION WHEN duplicate_object THEN null; END $$;

DO $$ BEGIN
    CREATE POLICY "Enable full access for service role"
        ON public.news_index_embeddings FOR ALL TO service_role USING (true);
EXCEPTION WHEN duplicate_object THEN null; END $$;

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
