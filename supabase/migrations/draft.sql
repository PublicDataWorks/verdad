-- ========================================================
-- 1. Create Necessary PostgreSQL Extensions
-- ========================================================

-- Enable pg_trgm extension for text similarity searches
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ========================================================
-- 2. Create Tables
-- ========================================================

-- --------------------------------------------------------
-- 2.1. Users Table
-- --------------------------------------------------------
CREATE TABLE draft_users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    display_name TEXT,
    role TEXT CHECK (role IN ('user', 'moderator', 'admin')) DEFAULT 'user',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Trigger to update 'updated_at' on row modification
CREATE OR REPLACE FUNCTION draft_update_timestamp()
RETURNS TRIGGER AS $$
BEGIN
   NEW.updated_at = NOW();
   RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER draft_users_update_timestamp
BEFORE UPDATE ON draft_users
FOR EACH ROW
EXECUTE PROCEDURE draft_update_timestamp();

-- --------------------------------------------------------
-- 2.2. Audio Files Table
-- --------------------------------------------------------
CREATE TABLE draft_audio_files (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    radio_station_name TEXT NOT NULL,
    radio_station_code TEXT NOT NULL,
    location_state TEXT NOT NULL,
    location_city TEXT NOT NULL,
    broadcast_date DATE NOT NULL,
    broadcast_time TIME NOT NULL,
    day_of_week TEXT NOT NULL,
    local_time_zone TEXT NOT NULL,
    file_path TEXT NOT NULL, -- Path or URL to the raw audio chunk
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE TRIGGER draft_audio_files_update_timestamp
BEFORE UPDATE ON draft_audio_files
FOR EACH ROW
EXECUTE PROCEDURE draft_update_timestamp();

-- --------------------------------------------------------
-- 2.3. Snippets Table
-- --------------------------------------------------------
CREATE TABLE draft_snippets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    audio_file_id UUID NOT NULL REFERENCES draft_audio_files(id) ON DELETE CASCADE,
    start_time TIME NOT NULL,
    end_time TIME NOT NULL,
    audio_clip_path TEXT NOT NULL, -- Path or URL to the generated audio clip
    brief_description TEXT, -- Added field for Stage 1 output
    transcription TEXT,
    translation TEXT,
    title TEXT,
    summary TEXT,
    explanation TEXT,
    disinformation_categories JSONB, -- Changed to JSONB to store categories with confidence scores
    language_primary TEXT,
    language_dialect TEXT,
    language_register TEXT, -- Formality level (e.g., formal, informal)
    context_before TEXT,
    context_after TEXT,
    confidence_overall INTEGER,
    confidence_categories JSONB, -- JSONB field for confidence scores per category
    emotional_tone JSONB, -- e.g., [{"emotion": "Fear", "intensity": 85, "explanation": "..."}]
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE TRIGGER draft_snippets_update_timestamp
BEFORE UPDATE ON draft_snippets
FOR EACH ROW
EXECUTE PROCEDURE draft_update_timestamp();

-- --------------------------------------------------------
-- 2.4. User Feedback Table
-- --------------------------------------------------------
CREATE TABLE draft_user_feedback (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    snippet_id UUID NOT NULL REFERENCES draft_snippets(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES draft_users(id) ON DELETE CASCADE,
    label TEXT, -- User-applied label
    upvotes INTEGER DEFAULT 0,
    comment TEXT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE TRIGGER draft_user_feedback_update_timestamp
BEFORE UPDATE ON draft_user_feedback
FOR EACH ROW
EXECUTE PROCEDURE draft_update_timestamp();

-- --------------------------------------------------------
-- 2.5. Heuristics Table
-- --------------------------------------------------------
CREATE TABLE draft_heuristics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    version_number INTEGER NOT NULL,
    content TEXT NOT NULL, -- The heuristic text
    llm_model TEXT NOT NULL, -- E.g., "Gemini 1.5 Flash"
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    change_explanation TEXT
);

-- Unique constraint on version_number to prevent duplicates
ALTER TABLE draft_heuristics ADD CONSTRAINT unique_heuristics_version_number UNIQUE (version_number);

CREATE TRIGGER draft_heuristics_update_timestamp
BEFORE UPDATE ON draft_heuristics
FOR EACH ROW
EXECUTE PROCEDURE draft_update_timestamp();

-- --------------------------------------------------------
-- 2.6. Prompt Versions Table
-- --------------------------------------------------------
CREATE TABLE draft_prompt_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    stage INTEGER NOT NULL CHECK (stage IN (1, 2)), -- Stage 1 or Stage 2
    version_number INTEGER NOT NULL,
    llm_model TEXT NOT NULL, -- E.g., "Gemini 1.5 Flash"
    prompt_text TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    change_explanation TEXT
);

-- Unique constraint on stage and version_number combination
ALTER TABLE draft_prompt_versions ADD CONSTRAINT unique_prompt_stage_version UNIQUE (stage, version_number);

CREATE TRIGGER draft_prompt_versions_update_timestamp
BEFORE UPDATE ON draft_prompt_versions
FOR EACH ROW
EXECUTE PROCEDURE draft_update_timestamp();

-- ========================================================
-- 3. Insert Dummy Data
-- ========================================================

-- --------------------------------------------------------
-- 3.1. Insert Dummy Users
-- --------------------------------------------------------
INSERT INTO draft_users (email, password_hash, display_name, role)
VALUES
('alice@example.com', 'hashed_password_1', 'Alice', 'user'),
('bob@example.com', 'hashed_password_2', 'Bob', 'moderator'),
('carol@example.com', 'hashed_password_3', 'Carol', 'admin');

-- --------------------------------------------------------
-- 3.2. Insert Dummy Audio Files
-- --------------------------------------------------------
INSERT INTO draft_audio_files (id, radio_station_name, radio_station_code, location_state, location_city, broadcast_date, broadcast_time, day_of_week, local_time_zone, file_path)
VALUES
(gen_random_uuid(), 'Radio Uno', 'RU', 'California', 'Los Angeles', '2023-11-01', '08:00:00', 'Wednesday', 'PST', '/path/to/raw_audio_file_1.mp3'),
(gen_random_uuid(), 'Radio Dos', 'RD', 'Texas', 'Houston', '2023-11-02', '09:30:00', 'Thursday', 'CST', '/path/to/raw_audio_file_2.mp3'),
(gen_random_uuid(), 'Radio Tres', 'RT', 'New York', 'New York City', '2023-11-03', '07:45:00', 'Friday', 'EST', '/path/to/raw_audio_file_3.mp3');

-- --------------------------------------------------------
-- 3.3. Insert Dummy Snippets
-- --------------------------------------------------------
INSERT INTO draft_snippets (
    id, audio_file_id, start_time, end_time, audio_clip_path, brief_description, transcription, translation, title, summary, explanation, disinformation_categories, language_primary, language_dialect, language_register, context_before, context_after, confidence_overall, confidence_categories, emotional_tone
)
VALUES
(
    gen_random_uuid(),
    (SELECT id FROM draft_audio_files WHERE radio_station_code = 'RU'),
    '00:05:30', '00:06:15',
    '/path/to/snippet_audio_clip_1.mp3',
    'Claims about government mind control via vaccines.',
    'Dicen que el gobierno quiere controlar nuestras mentes con las vacunas.',
    'They say the government wants to control our minds with the vaccines.',
    'Government Mind Control via Vaccines',
    'The speaker suggests that the government intends to control people\'s minds through vaccines.',
    'This snippet propagates the unfounded conspiracy theory that vaccines are a means of mind control.',
    '{"COVID-19 and Vaccination": null, "Conspiracy Theories": null}', -- Stage 1 categories without confidence scores
    'Spanish', 'Mexican Spanish', 'Informal',
    'Estamos viviendo tiempos difíciles, y hay muchas cosas que no nos dicen.',
    'Por eso debemos informarnos y proteger a nuestras familias.',
    95,
    '{"COVID-19 and Vaccination": 98, "Conspiracy Theories": 90}', -- Stage 2 confidence scores
    '[{"emotion": "Fear", "intensity": 85, "explanation": "The speaker expresses fear about government control through vaccines."}]'
),
(
    gen_random_uuid(),
    (SELECT id FROM draft_audio_files WHERE radio_station_code = 'RD'),
    '00:12:45', '00:13:30',
    '/path/to/snippet_audio_clip_2.mp3',
    'Discussion on economic problems caused by illegal immigrants.',
    'Los extranjeros ilegales están causando problemas económicos.',
    'Illegal foreigners are causing economic problems.',
    'Economic Impact of Illegal Immigrants',
    'The speaker claims that illegal immigrants are causing economic issues.',
    'This snippet portrays immigrants as threats to the economy, which is a common disinformation narrative.',
    '{"Immigration Policies": null}', -- Stage 1 categories without confidence scores
    'Spanish', 'Central American Spanish', 'Informal',
    'La situación económica es difícil para todos.',
    'Necesitamos soluciones reales, no más problemas.',
    90,
    '{"Immigration Policies": 90}',
    '[{"emotion": "Anger", "intensity": 80, "explanation": "The speaker expresses anger towards immigrants."}]'
);

-- --------------------------------------------------------
-- 3.4. Insert Dummy User Feedback
-- --------------------------------------------------------
INSERT INTO draft_user_feedback (id, snippet_id, user_id, label, upvotes, comment)
VALUES
(
    gen_random_uuid(),
    (SELECT id FROM draft_snippets WHERE title = 'Government Mind Control via Vaccines'),
    (SELECT id FROM draft_users WHERE email = 'alice@example.com'),
    'Conspiracy Theory',
    2,
    'I agree that this is spreading harmful misinformation.'
),
(
    gen_random_uuid(),
    (SELECT id FROM draft_snippets WHERE title = 'Economic Impact of Illegal Immigrants'),
    (SELECT id FROM draft_users WHERE email = 'bob@example.com'),
    'Anti-Immigrant Sentiment',
    1,
    'This kind of rhetoric is damaging to communities.'
);

-- --------------------------------------------------------
-- 3.5. Insert Dummy Heuristics
-- --------------------------------------------------------
INSERT INTO draft_heuristics (id, version_number, content, llm_model, change_explanation)
VALUES
(gen_random_uuid(), 1, 'Initial set of heuristics for disinformation detection.', 'Gemini 1.5 Flash', 'Seed heuristics.'),
(gen_random_uuid(), 2, 'Updated heuristics based on user feedback.', 'Gemini 1.5 Pro', 'Incorporated new patterns observed.');

-- --------------------------------------------------------
-- 3.6. Insert Dummy Prompt Versions
-- --------------------------------------------------------
INSERT INTO draft_prompt_versions (id, stage, version_number, llm_model, prompt_text, change_explanation)
VALUES
(gen_random_uuid(), 1, 1, 'Gemini 1.5 Flash', 'Stage 1 initial prompt text...', 'Initial prompt for Stage 1.'),
(gen_random_uuid(), 2, 1, 'Gemini 1.5 Pro', 'Stage 2 initial prompt text...', 'Initial prompt for Stage 2.');

-- ========================================================
-- 4. Notes
-- ========================================================

-- All 'id' fields are generated automatically using 'gen_random_uuid()'.

-- The 'brief_description' field has been added to 'draft_snippets' to store outputs from Stage 1.

-- The 'disinformation_categories' field in 'draft_snippets' has been changed to 'JSONB' to store multiple categories with optional confidence scores.

-- 'language_register' and 'confidence_categories' fields are included as per Stage 2 prompt requirements.

-- 'created_at' and 'updated_at' fields are set to 'NOT NULL' with default values.

-- Removed 'embedding' and related indexing as embeddings are handled externally.

-- Ensure that application logic retrieves and passes 'id' values to the LLMs as needed.

-- ========================================================
-- End of Migration File
-- ========================================================
