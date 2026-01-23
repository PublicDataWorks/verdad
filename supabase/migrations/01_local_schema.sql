-- Minimal Local Schema Migration
-- This is a cleaned-up version of the Supabase schema for local PostgreSQL
-- Removes: extensions, auth schema, Supabase roles, RLS policies

-- Create processing status enum
CREATE TYPE processing_status AS ENUM ('New', 'Processing', 'Processed', 'Error');

-- Core processing tables
CREATE TABLE audio_files (
    id UUID NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc'),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc'),
    radio_station_name TEXT NOT NULL,
    radio_station_code TEXT NOT NULL,
    location_state TEXT,
    location_city TEXT,
    recorded_at TIMESTAMPTZ NOT NULL,
    recording_day_of_week TEXT NOT NULL,
    file_path TEXT NOT NULL,
    file_name TEXT NOT NULL,
    file_size BIGINT NOT NULL,
    duration INTEGER,
    status processing_status NOT NULL DEFAULT 'New',
    error_message TEXT
);

CREATE TABLE stage_1_llm_responses (
    id UUID NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc'),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc'),
    audio_file UUID NOT NULL REFERENCES audio_files(id) ON DELETE CASCADE,
    detection_result JSONB,
    timestamped_transcription JSONB,
    status processing_status NOT NULL DEFAULT 'New',
    error_message TEXT,
    prompt_version UUID
);

CREATE TABLE snippets (
    id UUID NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc'),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc'),
    audio_file UUID NOT NULL REFERENCES audio_files(id) ON DELETE CASCADE,
    stage_1_llm_response UUID REFERENCES stage_1_llm_responses(id) ON DELETE CASCADE,
    file_path TEXT NOT NULL,
    file_size BIGINT NOT NULL,
    duration INTEGER NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL,
    start_time INTEGER NOT NULL,
    end_time INTEGER NOT NULL,
    transcription TEXT,
    previous_analysis JSONB,
    final_review JSONB,
    status processing_status NOT NULL DEFAULT 'New',
    error_message TEXT,
    hidden BOOLEAN DEFAULT FALSE,
    prompt_version UUID
);

CREATE TABLE snippet_embeddings (
    id UUID NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    snippet UUID NOT NULL REFERENCES snippets(id) ON DELETE CASCADE,
    embedding vector(768) NOT NULL
);

-- Prompt management tables
CREATE TABLE prompt_versions (
    id UUID NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    stage TEXT NOT NULL,
    version_number INTEGER NOT NULL,
    llm_model TEXT NOT NULL,
    prompt_text TEXT NOT NULL,
    system_instruction TEXT,
    output_schema JSONB,
    is_active BOOLEAN DEFAULT FALSE,
    change_explanation TEXT
);

CREATE TABLE heuristics (
    id UUID NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    stage TEXT NOT NULL,
    version_number INTEGER NOT NULL,
    content TEXT NOT NULL,
    is_active BOOLEAN DEFAULT FALSE,
    change_explanation TEXT
);

-- Optional: User management tables (simplified, no auth schema)
CREATE TABLE profiles (
    id UUID NOT NULL PRIMARY KEY,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    first_name TEXT,
    last_name TEXT,
    avatar_url TEXT,
    role TEXT
);

CREATE TABLE labels (
    id UUID NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    label TEXT NOT NULL UNIQUE,
    created_by UUID REFERENCES profiles(id),
    upvote_count INTEGER DEFAULT 0,
    like_count INTEGER DEFAULT 0,
    comment_count INTEGER DEFAULT 0
);

CREATE TABLE snippet_labels (
    id UUID NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    snippet UUID NOT NULL REFERENCES snippets(id) ON DELETE CASCADE,
    label UUID NOT NULL REFERENCES labels(id) ON DELETE CASCADE,
    applied_by UUID REFERENCES profiles(id),
    upvote_count INTEGER DEFAULT 0,
    CONSTRAINT unique_snippet_label UNIQUE (snippet, label)
);

CREATE TABLE label_upvotes (
    id UUID NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    snippet_label UUID NOT NULL REFERENCES snippet_labels(id) ON DELETE CASCADE,
    upvoted_by UUID NOT NULL REFERENCES profiles(id),
    CONSTRAINT unique_upvoted_by_snippet_label UNIQUE (upvoted_by, snippet_label)
);

CREATE TABLE user_star_snippets (
    id UUID NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    snippet UUID NOT NULL REFERENCES snippets(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES profiles(id),
    CONSTRAINT unique_user_snippet UNIQUE (user_id, snippet)
);

-- Draft tables for staging
CREATE TABLE draft_audio_files (
    audio_file_id UUID NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
    radio_station_name TEXT NOT NULL,
    radio_station_code TEXT NOT NULL,
    location_state TEXT NOT NULL,
    location_city TEXT NOT NULL,
    broadcast_date DATE NOT NULL,
    broadcast_time TIME NOT NULL,
    day_of_week TEXT NOT NULL,
    local_time_zone TEXT NOT NULL,
    file_path TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE draft_heuristics (
    heuristic_id UUID NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
    version_number INTEGER NOT NULL,
    content TEXT NOT NULL,
    llm_model TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    change_explanation TEXT
);

CREATE TABLE draft_prompt_versions (
    prompt_id UUID NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
    stage INTEGER NOT NULL CHECK (stage >= 1 AND stage <= 5),
    version_number INTEGER NOT NULL,
    llm_model TEXT NOT NULL,
    prompt_text TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    change_explanation TEXT,
    CONSTRAINT unique_stage_version UNIQUE (stage, version_number)
);

CREATE TABLE draft_snippets (
    snippet_id UUID NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
    audio_file_id UUID NOT NULL,
    start_time TIME NOT NULL,
    end_time TIME NOT NULL,
    audio_clip_path TEXT NOT NULL,
    transcription TEXT,
    translation TEXT,
    title TEXT,
    summary TEXT,
    explanation TEXT,
    disinformation_categories TEXT[],
    search_queries JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE draft_user_feedback (
    feedback_id UUID NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
    snippet_id UUID NOT NULL,
    user_id UUID NOT NULL,
    rating INTEGER CHECK (rating >= 1 AND rating <= 5),
    comment TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE draft_users (
    user_id UUID NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    name TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create indexes for performance
CREATE INDEX idx_audio_files_status ON audio_files(status);
CREATE INDEX idx_audio_files_recorded_at ON audio_files(recorded_at DESC);
CREATE INDEX idx_stage_1_status ON stage_1_llm_responses(status);
CREATE INDEX idx_stage_1_audio_file ON stage_1_llm_responses(audio_file);
CREATE INDEX idx_snippets_status ON snippets(status);
CREATE INDEX idx_snippets_audio_file ON snippets(audio_file);
CREATE INDEX idx_snippets_recorded_at ON snippets(recorded_at DESC);
CREATE INDEX idx_snippets_hidden ON snippets(hidden) WHERE hidden = FALSE;
CREATE INDEX idx_snippet_embeddings_snippet ON snippet_embeddings(snippet);
CREATE INDEX idx_prompt_versions_active ON prompt_versions(stage, is_active) WHERE is_active = TRUE;
CREATE INDEX idx_heuristics_active ON heuristics(stage, is_active) WHERE is_active = TRUE;

-- Unique constraints
ALTER TABLE draft_heuristics ADD CONSTRAINT unique_version_number UNIQUE (version_number);

-- Create basic functions (no extensions needed)
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Add update triggers
CREATE TRIGGER audio_files_update_updated_at BEFORE UPDATE ON audio_files
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER stage_1_llm_responses_update_updated_at BEFORE UPDATE ON stage_1_llm_responses
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER snippets_update_updated_at BEFORE UPDATE ON snippets
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER prompt_versions_update_updated_at BEFORE UPDATE ON prompt_versions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER heuristics_update_updated_at BEFORE UPDATE ON heuristics
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER labels_update_updated_at BEFORE UPDATE ON labels
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER snippet_labels_update_updated_at BEFORE UPDATE ON snippet_labels
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER label_upvotes_update_updated_at BEFORE UPDATE ON label_upvotes
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER user_star_snippets_update_updated_at BEFORE UPDATE ON user_star_snippets
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Grant permissions to verdad_user
GRANT ALL ON ALL TABLES IN SCHEMA public TO verdad_user;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO verdad_user;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO verdad_user;
