-- Knowledge Base Schema
-- Stores verified facts discovered during snippet reviews for RAG-based retrieval.
-- The KB is a source of truth — it only stores verified factual information.

-- Custom types
DO $$ BEGIN
    CREATE TYPE kb_entry_status AS ENUM ('active', 'superseded', 'deactivated');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- Table 1: kb_entries — Primary knowledge base
-- Each row is one verified fact at claim-level granularity.
CREATE TABLE IF NOT EXISTS public.kb_entries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Core content
    fact TEXT NOT NULL,
        -- The verified factual information. Always true.
        -- e.g., "Multiple peer-reviewed studies show immigrants commit crimes
        --  at lower rates than native-born US citizens."

    related_claim TEXT,
        -- Optional. The common disinformation claim this fact addresses.
        -- Included in the embedded document text, so it shapes the
        -- embedding vector and improves semantic retrieval quality.
        -- e.g., "Undocumented immigrants cause crime spikes"

    confidence_score INT NOT NULL DEFAULT 80
        CHECK (confidence_score >= 0 AND confidence_score <= 100),
        -- How confident we are in the accuracy of this fact (0-100).

    -- Temporal context
    valid_from TIMESTAMPTZ,
    valid_until TIMESTAMPTZ,
    is_time_sensitive BOOLEAN NOT NULL DEFAULT false,
    CHECK (valid_from IS NULL OR valid_until IS NULL OR valid_from <= valid_until),

    -- Categorization (reuses existing snippet taxonomy)
    disinformation_categories TEXT[] NOT NULL DEFAULT '{}',
    keywords TEXT[] NOT NULL DEFAULT '{}',

    -- Versioning (doubly-linked chain)
    version INT NOT NULL DEFAULT 1 CHECK (version >= 1),
    superseded_by UUID REFERENCES public.kb_entries(id) ON DELETE SET NULL,
    previous_version UUID REFERENCES public.kb_entries(id) ON DELETE SET NULL,

    -- Lifecycle
    status kb_entry_status NOT NULL DEFAULT 'active',
    deactivation_reason TEXT,

    -- Provenance
    created_by_snippet UUID REFERENCES public.snippets(id) ON DELETE SET NULL,
    created_by_model TEXT,
    notes TEXT
);

-- Table 2: kb_entry_sources — Evidence for each entry
-- Mirrors SearchResult from stage_3/models.py (same source_type tiers).
CREATE TABLE IF NOT EXISTS public.kb_entry_sources (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    kb_entry UUID NOT NULL REFERENCES public.kb_entries(id) ON DELETE CASCADE,

    url TEXT NOT NULL,
    source_name TEXT NOT NULL,
    source_type TEXT NOT NULL
        CHECK (source_type IN (
            'tier1_wire_service', 'tier1_factchecker', 'tier2_major_news',
            'tier3_regional_news', 'official_source', 'other'
        )),
    title TEXT,
    relevant_excerpt TEXT,
    publication_date DATE,
    relevance_to_claim TEXT NOT NULL DEFAULT 'provides_context'
        CHECK (relevance_to_claim IN (
            'supports_claim', 'contradicts_claim', 'provides_context', 'inconclusive'
        )),
    access_date DATE NOT NULL DEFAULT CURRENT_DATE
);

-- Table 3: kb_entry_embeddings — Vector storage for RAG
-- Same structure as snippet_embeddings. Uses OpenAI text-embedding-3-large (3072-dim).
CREATE TABLE IF NOT EXISTS public.kb_entry_embeddings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    kb_entry UUID NOT NULL UNIQUE REFERENCES public.kb_entries(id) ON DELETE CASCADE,
    embedded_document TEXT NOT NULL,
    document_token_count INT,
    embedding vector(3072) NOT NULL,
    model_name TEXT NOT NULL DEFAULT 'text-embedding-3-large',
    status TEXT NOT NULL DEFAULT 'Processed',
    error_message TEXT
);

-- Table 4: kb_entry_snippet_usage — Tracks snippet <-> KB relationships
CREATE TABLE IF NOT EXISTS public.kb_entry_snippet_usage (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    kb_entry UUID NOT NULL REFERENCES public.kb_entries(id) ON DELETE CASCADE,
    snippet UUID NOT NULL REFERENCES public.snippets(id) ON DELETE CASCADE,
    usage_type TEXT NOT NULL
        CHECK (usage_type IN ('used_for_review', 'triggered_creation', 'triggered_update')),
    similarity_score FLOAT,
    notes TEXT,
    UNIQUE (kb_entry, snippet, usage_type)
);

-- Indexes
-- Note: PK indexes on all tables, UNIQUE on kb_entry_embeddings(kb_entry),
-- and UNIQUE on kb_entry_snippet_usage(kb_entry, snippet, usage_type) are
-- created implicitly by their constraints and cover all point lookups.

-- Sources: FK lookup (used by search_kb_entries source aggregation + get_kb_entry_sources)
CREATE INDEX IF NOT EXISTS idx_kb_entry_sources_kb_entry ON public.kb_entry_sources (kb_entry);

-- Embeddings: sub-vector HNSW (drives search_kb_entries and find_duplicate_kb_entries)
CREATE INDEX IF NOT EXISTS kb_entry_embeddings_sub_vector_idx ON public.kb_entry_embeddings
    USING hnsw ((sub_vector(embedding, 512)::vector(512)) vector_ip_ops)
    WITH (m = 32, ef_construction = 400);

-- RLS
ALTER TABLE public.kb_entries ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.kb_entry_sources ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.kb_entry_embeddings ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.kb_entry_snippet_usage ENABLE ROW LEVEL SECURITY;

-- Grants
GRANT ALL ON TABLE public.kb_entries TO service_role;
GRANT ALL ON TABLE public.kb_entry_sources TO service_role;
GRANT ALL ON TABLE public.kb_entry_embeddings TO service_role;
GRANT ALL ON TABLE public.kb_entry_snippet_usage TO service_role;

GRANT SELECT ON TABLE public.kb_entries TO authenticated;
GRANT SELECT ON TABLE public.kb_entry_sources TO authenticated;
GRANT SELECT ON TABLE public.kb_entry_snippet_usage TO authenticated;

CREATE POLICY "Enable read access for authenticated users"
    ON public.kb_entries FOR SELECT TO authenticated USING (true);

CREATE POLICY "Enable full access for service role"
    ON public.kb_entries FOR ALL TO service_role USING (true);

CREATE POLICY "Enable read access for authenticated users"
    ON public.kb_entry_sources FOR SELECT TO authenticated USING (true);

CREATE POLICY "Enable full access for service role"
    ON public.kb_entry_sources FOR ALL TO service_role USING (true);

CREATE POLICY "Enable full access for service role"
    ON public.kb_entry_embeddings FOR ALL TO service_role USING (true);

CREATE POLICY "Enable read access for authenticated users"
    ON public.kb_entry_snippet_usage FOR SELECT TO authenticated USING (true);

CREATE POLICY "Enable full access for service role"
    ON public.kb_entry_snippet_usage FOR ALL TO service_role USING (true);
