-- VER-360: source credibility tiers (web evidence domains) and broadcast-source provenance (stations).
-- Seeded from data/source_credibility/*.csv by src/scripts/import_source_credibility.py; admin-editable.

CREATE TABLE IF NOT EXISTS public.source_credibility_domains (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    domain text NOT NULL UNIQUE,
    tier smallint NOT NULL CHECK (tier BETWEEN 1 AND 5),
    category text NOT NULL CHECK (
        category IN (
            'wire', 'public_broadcaster', 'fact_checker', 'official', 'broadsheet', 'broadcaster', 'regional',
            'magazine', 'state_controlled', 'conspiracy', 'hyperpartisan', 'disinformation_network', 'satire', 'other'
        )
    ),
    country text,
    languages text,
    owner text,
    rating_sources text,
    notes text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    updated_by text,
    CONSTRAINT source_credibility_domains_domain_normalized CHECK (domain = lower(domain) AND domain NOT LIKE 'www.%'),
    CONSTRAINT source_credibility_domains_low_tiers_cited CHECK (tier < 4 OR coalesce(rating_sources, '') <> '')
);

COMMENT ON TABLE public.source_credibility_domains IS
    'Domain -> credibility tier for web evidence. 1 trusted, 2 generally reliable, 3 default/mixed/unrated '
    '(also for domains absent here), 4 unreliable (never corroborates), 5 denied (excluded, blocks KB writes). '
    'See docs/SOURCE_CREDIBILITY.md.';

CREATE TABLE IF NOT EXISTS public.source_provenance (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    station_code text NOT NULL UNIQUE,
    provenance text NOT NULL CHECK (
        provenance IN (
            'state_controlled', 'state_funded_independent', 'public', 'commercial', 'community', 'religious', 'unknown'
        )
    ),
    owner text,
    country text,
    rating_sources text,
    notes text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    updated_by text
);

COMMENT ON TABLE public.source_provenance IS
    'Broadcast source (audio_files.radio_station_code) -> ownership provenance. Stations absent here are unknown.';

CREATE INDEX IF NOT EXISTS source_credibility_domains_tier_idx ON public.source_credibility_domains (tier);

ALTER TABLE public.source_credibility_domains ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.source_provenance ENABLE ROW LEVEL SECURITY;

GRANT ALL ON TABLE public.source_credibility_domains TO service_role;
GRANT ALL ON TABLE public.source_provenance TO service_role;
GRANT SELECT ON TABLE public.source_credibility_domains TO authenticated;
GRANT SELECT ON TABLE public.source_provenance TO authenticated;

CREATE POLICY "Enable read access for authenticated users"
    ON public.source_credibility_domains FOR SELECT TO authenticated USING (true);
CREATE POLICY "Enable full access for service role"
    ON public.source_credibility_domains FOR ALL TO service_role USING (true);

CREATE POLICY "Enable read access for authenticated users"
    ON public.source_provenance FOR SELECT TO authenticated USING (true);
CREATE POLICY "Enable full access for service role"
    ON public.source_provenance FOR ALL TO service_role USING (true);
