-- VER-332: sources (one row per station/channel/feed), feed_items (one row per feed entry,
-- deduped on source_id + external_item_id), nullable audio_files.source_id.

CREATE TABLE IF NOT EXISTS public.sources (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    type text NOT NULL CHECK (type IN ('radio', 'youtube', 'podcast')),
    -- station code, YouTube channel id, or podcast feed URL
    external_id text NOT NULL,
    display_name text NOT NULL,
    location_state text,
    language text,
    -- radio: ffmpeg input URL. youtube/podcast: null
    stream_url text,
    -- youtube: [uploads feed, livestreams feed]. podcast: [feed]. radio: []
    feed_urls jsonb NOT NULL DEFAULT '[]'::jsonb,
    enabled boolean NOT NULL DEFAULT true,
    poll_interval_seconds integer NOT NULL DEFAULT 900,
    last_polled_at timestamptz,
    last_success_at timestamptz,
    consecutive_failures integer NOT NULL DEFAULT 0,
    last_error text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (type, external_id)
);

CREATE OR REPLACE TRIGGER sources_handle_updated_at
    BEFORE UPDATE ON public.sources
    FOR EACH ROW EXECUTE FUNCTION moddatetime('updated_at');

CREATE TABLE IF NOT EXISTS public.feed_items (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    source_id uuid NOT NULL REFERENCES public.sources(id) ON DELETE CASCADE,
    -- YouTube video id or RSS guid
    external_item_id text NOT NULL,
    title text,
    item_url text,
    published_at timestamptz,
    duration_seconds integer,
    is_live_recording boolean NOT NULL DEFAULT false,
    status text NOT NULL DEFAULT 'new'
        CHECK (status IN ('new', 'downloading', 'downloaded', 'failed', 'skipped')),
    attempts integer NOT NULL DEFAULT 0,
    last_error text,
    audio_file_id uuid REFERENCES public.audio_files(id) ON DELETE SET NULL,
    UNIQUE (source_id, external_item_id)
);

CREATE OR REPLACE TRIGGER feed_items_handle_updated_at
    BEFORE UPDATE ON public.feed_items
    FOR EACH ROW EXECUTE FUNCTION moddatetime('updated_at');

-- downloader claims work by status
CREATE INDEX IF NOT EXISTS idx_feed_items_status_published
    ON public.feed_items (status, published_at);

ALTER TABLE public.audio_files
    ADD COLUMN IF NOT EXISTS source_id uuid REFERENCES public.sources(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_audio_files_source_id
    ON public.audio_files (source_id);

-- no policies: service role only
ALTER TABLE public.sources ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.feed_items ENABLE ROW LEVEL SECURITY;
