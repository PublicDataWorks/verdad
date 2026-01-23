# Complete PostgreSQL Database Setup Guide

This guide will walk you through setting up your local PostgreSQL database from scratch for the political debate fact-checking system.

## Prerequisites

- PostgreSQL 16 installed
- pgvector extension available
- Database `verdad_debates` created
- User `verdad_user` created with password

---

## Step-by-Step Setup

### Step 1: Verify Database Connection

```bash
# Test that you can connect to the database
psql -U verdad_user -d verdad_debates -c "SELECT version();"
```

**Expected output:** Should show PostgreSQL version 16.x

---

### Step 2: Install Required Extensions

```bash
# Install pgvector extension (required for embeddings)
psql -U verdad_user -d verdad_debates -c "CREATE EXTENSION IF NOT EXISTS vector;"

# Verify extension is installed
psql -U verdad_user -d verdad_debates -c "\dx"
```

Expected output: Should list `vector` in the extensions table.

---

### Step 3: Reset Database (If Needed)

If you previously ran migrations and encountered errors, reset the database first:

```bash
# Option 1: Reset as postgres superuser (recommended)
sudo -u postgres psql -d verdad_debates -f supabase/migrations/00_reset_database.sql

# Option 2: Drop and recreate the database completely
sudo -u postgres psql << 'EOF'
DROP DATABASE IF EXISTS verdad_debates;
CREATE DATABASE verdad_debates OWNER verdad_user;
\c verdad_debates
CREATE EXTENSION vector;
GRANT ALL ON SCHEMA public TO verdad_user;
EOF
```

**When to use this:**
- After getting "already exists" errors
- To start completely fresh
- If previous migrations partially failed

**Skip this step** if your database is brand new and empty.

---

### Step 4: Apply Local Schema Migration

This creates all tables, types, and indexes for local PostgreSQL (without Supabase dependencies).

```bash
psql -U verdad_user -d verdad_debates -f supabase/migrations/01_local_schema.sql
```

**What this does:**
- Creates enum type: `processing_status` (New, Processing, Processed, Error)
- Creates tables: `audio_files`, `stage_1_llm_responses`, `snippets`, `snippet_embeddings`
- Creates optional tables: `profiles`, `labels`, `prompt_versions`, `heuristics`
- Creates indexes for performance
- Creates update triggers (replaces moddatetime extension)
- No dependencies on Supabase extensions or `auth` schema

**Expected output:** Should see multiple `CREATE TABLE`, `CREATE INDEX`, `CREATE TRIGGER` messages without errors.

**Note:** This replaces the original `20241029135348_remote_schema.sql` which has Supabase-specific dependencies.

---

### Step 5: Apply Processing Pipeline RPC Functions

These 5 functions are critical for the processing pipeline's task reservation system. They must be applied individually.

```bash
# Stage 1: Reserve audio file for initial detection
psql -U verdad_user -d verdad_debates -f supabase/database/sql/fetch_a_new_audio_file_and_reserve_it.sql

# Stage 2: Reserve stage-1 response for audio clipping
psql -U verdad_user -d verdad_debates -f supabase/database/sql/fetch_a_new_stage_1_llm_response_and_reserve_it.sql

# Stage 3: Reserve snippet for in-depth analysis
psql -U verdad_user -d verdad_debates -f supabase/database/sql/fetch_a_new_snippet_and_reserve_it.sql

# Stage 4: Reserve snippet for human review
psql -U verdad_user -d verdad_debates -f supabase/database/sql/fetch_a_ready_for_review_snippet_and_reserve_it.sql

# Stage 5: Get snippet without embedding
psql -U verdad_user -d verdad_debates -f supabase/database/sql/fetch_a_snippet_that_has_no_embedding.sql
```

**What these do:**
- Use atomic `UPDATE ... FOR UPDATE SKIP LOCKED` pattern to prevent race conditions
- Return `jsonb` with embedded join data (e.g., audio_file details in snippet)
- Auto-update status: `New` → `Processing` (or `Ready for review` → `Reviewing`)
- Enable distributed processing across multiple workers

**Expected output:** Should see `CREATE OR REPLACE FUNCTION` messages for each file.

---

### Step 6: (Optional) Apply Additional Functions for Web UI

If you plan to build a web interface or use advanced features, apply these:

```bash
# Full-text search
psql -U verdad_user -d verdad_debates -f supabase/database/sql/full_text_search_index.sql

# Similarity search (requires embeddings)
psql -U verdad_user -d verdad_debates -f supabase/database/sql/search_related_snippets.sql

# Label management
psql -U verdad_user -d verdad_debates -f supabase/database/sql/create_apply_and_upvote_label_function.sql

# User functions
psql -U verdad_user -d verdad_debates -f supabase/database/sql/setup_profile_function.sql
```

**Note:** These are NOT required for the processing pipeline to work.

---

### Step 7: Verify Schema Setup

```bash
# Check that all main tables exist
psql -U verdad_user -d verdad_debates -c "
SELECT table_name 
FROM information_schema.tables 
WHERE table_schema = 'public' 
  AND table_type = 'BASE TABLE'
ORDER BY table_name;
"
```

**Expected tables (minimum):**
- `audio_files` ✓
- `stage_1_llm_responses` ✓
- `snippets` ✓
- `snippet_embeddings` ✓

**Plus additional tables:**
- `profiles`, `labels`, `snippet_labels`, `label_upvotes`
- `user_star_snippets`, `prompt_versions`, `heuristics`
- `draft_*` tables for staging

---

### Step 8: Verify Processing Pipeline Functions

```bash
# List the 5 critical RPC functions
psql -U verdad_user -d verdad_debates -c "
SELECT routine_name, routine_schema
FROM information_schema.routines 
WHERE routine_schema = 'public' 
  AND routine_type = 'FUNCTION'
  AND routine_name LIKE 'fetch_%'
ORDER BY routine_name;
"
```

**Expected functions:**
1. `fetch_a_new_audio_file_and_reserve_it` ✓
2. `fetch_a_new_snippet_and_reserve_it` ✓
3. `fetch_a_new_stage_1_llm_response_and_reserve_it` ✓
4. `fetch_a_ready_for_review_snippet_and_reserve_it` ✓
5. `fetch_a_snippet_that_has_no_embedding` ✓

---

### Step 9: Verify Processing Status Enum

```bash
psql -U verdad_user -d verdad_debates -c "
SELECT unnest(enum_range(NULL::processing_status)) AS status_value;
"
```

**Expected values:**
```
 status_value
--------------
 New
 Processing
 Processed
 Error
```

---

### Step 10: Test Connection from Python

```bash
python3 -c "
from src.processing_pipeline.postgres_client import PostgresClient
db = PostgresClient()
print('✅ Database connection successful!')
db.close()
"
```

**Expected output:** `✅ Database connection successful!`

**If you get import errors:** Run `poetry install` first.

---

### Step 11: Create Storage Directory Structure

```bash
# Create base storage directory
mkdir -p ~/verdad_debates_storage/audio
mkdir -p ~/verdad_debates_storage/snippets

# Verify directories were created
ls -la ~/verdad_debates_storage/
```

**Expected output:** Should show `audio/` and `snippets/` directories.

---

### Step 12: Update Environment Variables

Create or update your `.env` file in the project root:

```bash
cat > .env << 'EOF'
# Database Connection
DATABASE_URL=postgresql://verdad_user:your_password@localhost:5432/verdad_debates

# Local Storage
STORAGE_PATH=~/verdad_debates_storage

# AI Services
GOOGLE_GEMINI_KEY=your_gemini_api_key
OPENAI_API_KEY=your_openai_api_key

# Search Engine (optional)
SEARXNG_URL=http://localhost:8080

# Remove these old cloud variables:
# SUPABASE_URL=
# SUPABASE_KEY=
# R2_ENDPOINT_URL=
# R2_ACCESS_KEY_ID=
# R2_SECRET_ACCESS_KEY=
# R2_BUCKET_NAME=
EOF
```

**Important:** Replace `your_password`, `your_gemini_api_key`, and `your_openai_api_key` with actual values.

---

### Step 13: Insert Test Audio File Record

```bash
# Create a test audio file entry in the database
psql -U verdad_user -d verdad_debates << 'EOF'
INSERT INTO audio_files (
    file_path, 
    file_name,
    file_size, 
    duration,
    recorded_at, 
    recording_day_of_week,
    radio_station_name, 
    radio_station_code,
    location_state,
    location_city,
    status
) VALUES (
    'test/debate_sample_2026.mp3',
    'debate_sample_2026.mp3',
    5242880,
    1800,
    NOW() - INTERVAL '1 hour',
    'Thursday',
    'Test Debate Channel',
    'TEST',
    'Test State',
    'Test City',
    'New'
) RETURNING id, file_name, status, recorded_at;
EOF
```

**Expected output:** Should return the UUID, file name, status='New', and timestamp.

---

### Step 14: Copy Test Audio File to Storage

```bash
# Copy your MP3 file to the storage directory
# Replace /path/to/your/audio.mp3 with your actual file
mkdir -p ~/verdad_debates_storage/test
cp /path/to/your/audio.mp3 ~/verdad_debates_storage/test/debate_sample_2026.mp3

# Verify file exists
ls -lh ~/verdad_debates_storage/test/debate_sample_2026.mp3
```

**Note:** The file path in the database must match the actual file location in storage.

---

### Step 15: Verify Test Record

```bash
# Check that the audio file record exists and is ready
psql -U verdad_user -d verdad_debates -c "
SELECT 
    id, 
    file_name, 
    radio_station_name,
    status, 
    created_at,
    recorded_at
FROM audio_files 
WHERE status = 'New'
ORDER BY created_at DESC 
LIMIT 5;
"
```

**Expected output:** Should show your test audio file with status='New'.

---

### Step 16: Test RPC Function

```bash
# Test that the Stage 1 function can fetch the audio file
psql -U verdad_user -d verdad_debates -c "
SELECT fetch_a_new_audio_file_and_reserve_it();
"
```

**Expected behavior:**
- Returns a jsonb object with audio file details
- Status automatically changes from 'New' → 'Processing'

**To reset status for testing:**
```bash
psql -U verdad_user -d verdad_debates -c "
UPDATE audio_files SET status = 'New' WHERE status = 'Processing';
"
```

---

## Troubleshooting

### Understanding the Original Schema Migration Errors

If you tried to run `supabase/migrations/20241029135348_remote_schema.sql` directly, you encountered multiple errors. Here's why and how to fix them:

#### 1. Extension Errors (Missing Supabase Extensions)
```
ERROR: extension "http" is not available
ERROR: extension "hypopg" is not available
ERROR: extension "pgroonga" is not available
ERROR: extension "supa_queue" is not available
```

**Why:** These are Supabase-specific PostgreSQL extensions that aren't available in standard PostgreSQL installations.

**Solution:** Use `supabase/migrations/01_local_schema.sql` instead. It has no external extension dependencies (only the standard `vector` extension).

#### 2. "Already Exists" Collision Errors
```
ERROR: type "processing_status" already exists
ERROR: relation "audio_files" already exists
```

**Why:** You ran the migration before and it partially succeeded, leaving some objects in the database.

**Solution:** Reset the database using Step 3:
```bash
sudo -u postgres psql -d verdad_debates -f supabase/migrations/00_reset_database.sql
```

#### 3. Missing 'auth' Schema Errors
```
ERROR: schema "auth" does not exist
ERROR: constraint "profiles_id_fkey" ... references auth.users
```

**Why:** Supabase has a special `auth` schema with a `users` table for authentication. Local PostgreSQL doesn't have this.

**Solution:** `01_local_schema.sql` removes all foreign keys to `auth.users`. The `profiles` table no longer requires authentication integration.

#### 4. Missing Role Errors
```
ERROR: role "anon" does not exist
ERROR: role "authenticated" does not exist  
ERROR: role "service_role" does not exist
```

**Why:** These are Supabase API roles used for row-level security (RLS) policies. They control access through the Supabase REST API.

**Solution:** `01_local_schema.sql` removes all RLS policies. For local processing, you connect directly as `verdad_user` without API roles.

#### 5. Missing moddatetime Extension
```
ERROR: function moddatetime() does not exist
ERROR: permission denied to create extension "moddatetime"
```

**Why:** `moddatetime` is a Supabase extension that auto-updates `updated_at` timestamps.

**Solution:** `01_local_schema.sql` includes a custom trigger function `update_updated_at_column()` that does the same thing without requiring the extension.

---

### Error: "role does not exist"

```bash
# Create the user as postgres superuser
sudo -u postgres psql -c "CREATE USER verdad_user WITH PASSWORD 'your_password';"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE verdad_debates TO verdad_user;"
```

### Error: "database does not exist"

```bash
# Create the database
sudo -u postgres createdb -O verdad_user verdad_debates

# Or create it manually
sudo -u postgres psql -c "CREATE DATABASE verdad_debates OWNER verdad_user;"
```

### Error: "extension vector does not exist"

```bash
# Install pgvector system package (openSUSE)
sudo zypper install postgresql16-pgvector

# For other systems, see: https://github.com/pgvector/pgvector#installation

# Then enable it in the database
psql -U verdad_user -d verdad_debates -c "CREATE EXTENSION vector;"
```

### Error: "permission denied for schema public"

```bash
# Grant all permissions to your user
sudo -u postgres psql -d verdad_debates << 'EOF'
GRANT ALL ON SCHEMA public TO verdad_user;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO verdad_user;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO verdad_user;
GRANT ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA public TO verdad_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO verdad_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO verdad_user;
EOF
```

### Error: "type processing_status does not exist"

This means Step 3 (main schema migration) failed or wasn't applied.

```bash
# Check if it exists
psql -U verdad_user -d verdad_debates -c "\dT processing_status"

# If not, re-apply the schema migration
psql -U verdad_user -d verdad_debates -f supabase/migrations/20241029135348_remote_schema.sql
```

### Error: psycopg2 import errors in Python

```bash
# Ensure dependencies are installed
poetry lock
poetry install

# Verify psycopg2-binary is in pyproject.toml
grep psycopg2 pyproject.toml
```

### Database Functions Return Empty/None

**Problem:** RPC functions return `NULL` instead of data.

**Solution:** The functions use `FOR UPDATE SKIP LOCKED`, which means if another process is already processing a record, it will skip it. Check for stuck records:

```bash
# Find records stuck in 'Processing' status
psql -U verdad_user -d verdad_debates -c "
SELECT 'audio_files' AS table, COUNT(*) AS stuck_count 
FROM audio_files WHERE status = 'Processing'
UNION ALL
SELECT 'stage_1_llm_responses', COUNT(*) 
FROM stage_1_llm_responses WHERE status = 'Processing'
UNION ALL
SELECT 'snippets', COUNT(*) 
FROM snippets WHERE status = 'Processing';
"

# Reset them to 'New' if needed
psql -U verdad_user -d verdad_debates << 'EOF'
UPDATE audio_files SET status = 'New' WHERE status = 'Processing';
UPDATE stage_1_llm_responses SET status = 'New' WHERE status = 'Processing';
UPDATE snippets SET status = 'New' WHERE status = 'Processing';
EOF
```

---

## Next Steps: Run the Processing Pipeline

### Option 1: Run All Stages Manually

```bash
# Start Prefect server (in a separate terminal)
poetry run prefect server start

# In another terminal, run Stage 1
poetry run python -c "
from src.processing_pipeline.stage_1 import initial_disinformation_detection
initial_disinformation_detection(audio_file_id=None, limit=1)
"
```

### Option 2: Use the Processing Scripts

```bash
# Start processing worker
./scripts/start_processing.sh
```

---

## Database Schema Overview

### Core Processing Pipeline Tables

#### 1. `audio_files` - Source audio recordings
```
Columns: id, file_path, file_size, duration, recorded_at, 
         radio_station_name, radio_station_code, status
Status Flow: New → Processing → Processed/Error
```

#### 2. `stage_1_llm_responses` - Initial LLM detection results
```
Columns: id, audio_file_id, detection_result, 
         timestamped_transcription, status
Links to: audio_files
Status Flow: New → Processing → Processed/Error
```

#### 3. `snippets` - Extracted disinformation clips
```
Columns: id, audio_file_id, stage_1_llm_response, file_path,
         transcription, previous_analysis, final_review, status
Links to: audio_files, stage_1_llm_responses
Status Flow: New → Processing → Ready for review → Reviewing → Processed/Error
```

#### 4. `snippet_embeddings` - Vector embeddings for similarity
```
Columns: id, snippet, embedding (vector(768))
Links to: snippets
Used by: Stage 5, similarity search
```

### Processing Status Flow

```mermaid
audio_files (New)
  ↓ Stage 1: Transcription + Detection
stage_1_llm_responses (New)
  ↓ Stage 2: Audio Clipping
snippets (New)
  ↓ Stage 3: In-Depth Analysis
snippets (Ready for review)
  ↓ Stage 4: Human Review
snippets (Processed)
  ↓ Stage 5: Generate Embeddings
snippet_embeddings
```

### Function Return Formats

The 5 RPC functions return `jsonb` with the following structures:

**Stage 1** - `fetch_a_new_audio_file_and_reserve_it()`:
```json
{
  "id": "uuid",
  "file_path": "test/audio.mp3",
  "file_name": "audio.mp3",
  "recorded_at": "2026-01-23T10:00:00+00:00",
  "radio_station_name": "Test Station",
  "status": "Processing"
}
```

**Stage 2** - `fetch_a_new_stage_1_llm_response_and_reserve_it()`:
```json
{
  "id": "uuid",
  "detection_result": {...},
  "timestamped_transcription": {...},
  "audio_file": {
    "id": "uuid",
    "file_path": "test/audio.mp3",
    "recorded_at": "2026-01-23T10:00:00+00:00"
  }
}
```

**Stage 3** - `fetch_a_new_snippet_and_reserve_it()`:
```json
{
  "id": "uuid",
  "file_path": "test/snippets/snippet.mp3",
  "transcription": "...",
  "audio_file": {
    "radio_station_name": "...",
    "recorded_at": "..."
  },
  "stage_1_llm_response": {...}
}
```

---

## Verification Checklist

- [ ] PostgreSQL 16 installed and running
- [ ] Database `verdad_debates` created
- [ ] User `verdad_user` created with proper permissions
- [ ] pgvector extension installed and enabled
- [ ] Main schema migration applied successfully (20241029135348_remote_schema.sql)
- [ ] 5 RPC functions applied from `supabase/database/sql/`:
  - [ ] fetch_a_new_audio_file_and_reserve_it.sql
  - [ ] fetch_a_new_stage_1_llm_response_and_reserve_it.sql
  - [ ] fetch_a_new_snippet_and_reserve_it.sql
  - [ ] fetch_a_ready_for_review_snippet_and_reserve_it.sql
  - [ ] fetch_a_snippet_that_has_no_embedding.sql
- [ ] All expected tables exist (verified in Step 6)
- [ ] All expected functions exist (verified in Step 7)
- [ ] Python connection test passes (Step 9)
- [ ] Storage directories created (Step 10)
- [ ] .env file updated with DATABASE_URL and STORAGE_PATH (Step 11)
- [ ] Test audio file record inserted (Step 12)
- [ ] Test audio file copied to storage (Step 13)
- [ ] RPC function test successful (Step 15)
- [ ] psycopg2-binary installed via poetry

Once all items are checked, your database is ready for processing!

---

## Files Modified in This Migration

For reference, here are the files that were updated to support local PostgreSQL:

**Created:**
- `src/processing_pipeline/postgres_client.py` - PostgreSQL adapter
- `src/processing_pipeline/local_storage.py` - Local filesystem storage

**Modified:**
- `pyproject.toml` - Removed supabase, added psycopg2-binary
- `src/main.py` - Updated imports
- `src/processing_pipeline/__init__.py` - Updated exports
- `src/processing_pipeline/stage_1.py` - Client initialization
- `src/processing_pipeline/stage_2.py` - Client initialization  
- `src/processing_pipeline/stage_3.py` - Client initialization
- `src/processing_pipeline/stage_4.py` - Client initialization
- `src/processing_pipeline/stage_5.py` - Client initialization

**Deleted:**
- All radio recording modules (completed in previous step)
- `supabase/migrations/20260123000000_add_rpc_functions.sql` (incorrect, use database/sql/ instead)

---

### Step 3: Apply Main Schema Migration

This creates all tables, types, indexes, and constraints.

```bash
psql -U verdad_user -d verdad_debates -f supabase/migrations/20241029135348_remote_schema.sql
```

**What this does:**
- Creates enum type: `processing_status`
- Creates tables: `audio_files`, `stage_1_llm_responses`, `snippets`, `snippet_embeddings`, `profiles`, `labels`, etc.
- Creates indexes for performance
- Sets up foreign key relationships
- Configures row-level security policies

Expected output: Should see multiple `CREATE TABLE`, `CREATE INDEX`, `CREATE POLICY` messages without errors.

---

### Step 4: Apply RPC Functions Migration

This creates the 5 critical functions for task reservation across the processing pipeline.

```bash
psql -U verdad_user -d verdad_debates -f supabase/migrations/20260123000000_add_rpc_functions.sql
```

**What this does:**
- Creates `fetch_a_new_audio_file_and_reserve_it()` - Stage 1
- Creates `fetch_a_new_stage_1_llm_response_and_reserve_it()` - Stage 2
- Creates `fetch_a_new_snippet_and_reserve_it()` - Stage 3
- Creates `fetch_a_ready_for_review_snippet_and_reserve_it()` - Stage 4
- Creates `fetch_a_snippet_that_has_no_embedding()` - Stage 5
- Creates performance indexes

Expected output: Should see `CREATE FUNCTION` and `CREATE INDEX` messages.

---

### Step 5: Verify Schema Setup

```bash
# Check that all main tables exist
psql -U verdad_user -d verdad_debates -c "
SELECT table_name 
FROM information_schema.tables 
WHERE table_schema = 'public' 
ORDER BY table_name;
"
```

**Expected tables:**
- `audio_files`
- `stage_1_llm_responses`
- `snippets`
- `snippet_embeddings`
- `profiles`
- `labels`
- `snippet_labels`
- `label_upvotes`
- `user_star_snippets`
- `prompt_versions`
- `heuristics`
- ... and more

---

### Step 6: Verify RPC Functions

```bash
# List all functions
psql -U verdad_user -d verdad_debates -c "
SELECT routine_name 
FROM information_schema.routines 
WHERE routine_schema = 'public' 
  AND routine_type = 'FUNCTION'
  AND routine_name LIKE 'fetch%'
ORDER BY routine_name;
"
```

**Expected functions:**
- `fetch_a_new_audio_file_and_reserve_it`
- `fetch_a_new_snippet_and_reserve_it`
- `fetch_a_new_stage_1_llm_response_and_reserve_it`
- `fetch_a_ready_for_review_snippet_and_reserve_it`
- `fetch_a_snippet_that_has_no_embedding`

---

### Step 7: Verify Processing Status Enum

```bash
psql -U verdad_user -d verdad_debates -c "
SELECT unnest(enum_range(NULL::processing_status));
"
```

**Expected values:**
- `New`
- `Processing`
- `Processed`
- `Error`

---

### Step 8: Test Connection from Python

```bash
python3 -c "
from src.processing_pipeline.postgres_client import PostgresClient
db = PostgresClient()
print('✅ Connection successful!')
db.close()
"
```

Expected output: `✅ Connection successful!`

---

### Step 9: Insert Test Audio File

```bash
# Create a test audio file entry
psql -U verdad_user -d verdad_debates << 'EOF'
INSERT INTO audio_files (
    file_path, 
    file_name,
    file_size, 
    duration,
    recorded_at, 
    recording_day_of_week,
    radio_station_name, 
    radio_station_code,
    location_state,
    location_city,
    status
) VALUES (
    'test/debate_sample_2026.mp3',
    'debate_sample_2026.mp3',
    1048576,
    3600,
    NOW(),
    'Thursday',
    'Test Station',
    'TEST',
    'Test State',
    'Test City',
    'New'
) RETURNING id, file_path, status;
EOF
```

**What this does:**
- Creates a test audio file record with status='New'
- Returns the generated UUID and file path
- This file will be picked up by Stage 1 processing

---

### Step 10: Verify Test Record

```bash
# Check that the record exists
psql -U verdad_user -d verdad_debates -c "
SELECT id, file_name, status, created_at 
FROM audio_files 
ORDER BY created_at DESC 
LIMIT 5;
"
```

You should see your test record with status='New'.

---

## Troubleshooting

### Error: "role does not exist"

```bash
# Create the user
sudo -u postgres psql -c "CREATE USER verdad_user WITH PASSWORD 'your_password';"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE verdad_debates TO verdad_user;"
```

### Error: "database does not exist"

```bash
# Create the database
sudo -u postgres createdb -O verdad_user verdad_debates
```

### Error: "extension vector does not exist"

```bash
# Install pgvector system package (openSUSE)
sudo zypper install postgresql16-pgvector

# Then in psql:
psql -U verdad_user -d verdad_debates -c "CREATE EXTENSION vector;"
```

### Error: "permission denied for schema public"

```bash
sudo -u postgres psql -d verdad_debates -c "GRANT ALL ON SCHEMA public TO verdad_user;"
sudo -u postgres psql -d verdad_debates -c "GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO verdad_user;"
sudo -u postgres psql -d verdad_debates -c "GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO verdad_user;"
```

### Error: psycopg2 import errors in Python

```bash
# Make sure dependencies are installed
poetry lock
poetry install
```

---

## Next Steps

After completing this setup:

1. **Copy your MP3 file** to the storage directory:
   ```bash
   mkdir -p ~/verdad_debates_storage/test
   cp /path/to/your/debate.mp3 ~/verdad_debates_storage/test/debate_sample_2026.mp3
   ```

2. **Update your .env file** with database credentials:
   ```env
   DATABASE_URL=postgresql://verdad_user:your_password@localhost:5432/verdad_debates
   STORAGE_PATH=~/verdad_debates_storage
   ```

3. **Start Prefect server** (if not already running):
   ```bash
   prefect server start
   ```

4. **Run Stage 1 processing**:
   ```bash
   poetry run python -c "
   from src.processing_pipeline.stage_1 import initial_disinformation_detection
   initial_disinformation_detection(audio_file_id=None, limit=1)
   "
   ```

---

## Schema Overview

### Core Processing Tables

**audio_files** - Uploaded audio files
- Columns: id, file_path, file_size, duration, recorded_at, status
- Status flow: New → Processing → Processed/Error

**stage_1_llm_responses** - LLM detection results
- Columns: id, audio_file_id, detection_result, timestamped_transcription, status
- Links to: audio_files

**snippets** - Extracted disinformation clips
- Columns: id, audio_file_id, file_path, transcription, previous_analysis, final_review, status
- Links to: audio_files, stage_1_llm_responses

**snippet_embeddings** - Vector embeddings for similarity search
- Columns: id, snippet_id, embedding (vector(768))
- Links to: snippets

### Processing Status Flow

```
audio_files (New) 
  → Stage 1 → stage_1_llm_responses (New)
    → Stage 2 → snippets (New)
      → Stage 3 → snippets (Ready for review)
        → Stage 4 → snippets (Processed)
          → Stage 5 → snippet_embeddings
```

---

## Verification Checklist

- [ ] PostgreSQL 16 installed and running
- [ ] Database `verdad_debates` created
- [ ] User `verdad_user` created with proper permissions
- [ ] pgvector extension installed
- [ ] Main schema migration applied successfully
- [ ] RPC functions migration applied successfully
- [ ] All expected tables exist
- [ ] All expected functions exist
- [ ] Python connection test passes
- [ ] Test audio file record created
- [ ] Storage directories created
- [ ] .env file updated

Once all items are checked, your database is ready for processing!
