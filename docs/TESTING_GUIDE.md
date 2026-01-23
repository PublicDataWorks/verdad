# Testing & Running the Political Debate Fact-Checking System

This guide walks you through testing your local setup and running the complete processing pipeline.

## Prerequisites Checklist

Before testing, ensure you've completed:
- [x] PostgreSQL database setup (`01_local_schema.sql` applied)
- [x] 5 RPC functions installed
- [x] `.env` file configured with DATABASE_URL and STORAGE_PATH
- [x] `poetry install` completed
- [x] Storage directories created (`~/verdad_debates_storage/`)

---

## Quick Test: Verify Everything Works

### Test 1: Database Connection

```bash
# Test Python can connect to PostgreSQL
poetry run python -c "
from src.processing_pipeline.postgres_client import PostgresClient
db = PostgresClient()
print('✅ Database connection successful!')
print(f'Connection: {db.connection_string}')
db.close()
"
```

**Expected:** `✅ Database connection successful!`

---

### Test 2: Verify RPC Functions

```bash
# Check all 5 RPC functions exist
psql -U verdad_user -d verdad_debates -c "
SELECT routine_name 
FROM information_schema.routines 
WHERE routine_schema = 'public' 
  AND routine_name LIKE 'fetch_%'
ORDER BY routine_name;
"
```

**Expected:** Should list 5 functions:
- fetch_a_new_audio_file_and_reserve_it
- fetch_a_new_snippet_and_reserve_it
- fetch_a_new_stage_1_llm_response_and_reserve_it
- fetch_a_ready_for_review_snippet_and_reserve_it
- fetch_a_snippet_that_has_no_embedding

---

### Test 3: Storage Directories

```bash
# Verify storage is accessible
ls -la ~/verdad_debates_storage/
```

**Expected:** Should show `audio/` and `snippets/` directories.

---

## Full Pipeline Test: Process a Test Audio File

### Step 1: Load Prompts into Database

The processing pipeline requires prompts to be loaded into the database:

```bash
# Load all prompts and heuristics
poetry run python scripts/load_prompts.py
```

**Expected output:**
```
🚀 Loading prompts into database...
✅ Loaded gemini_timestamped_transcription prompt (v1)
✅ Loaded stage_1 prompt (v1)
✅ Loaded stage_3 prompt (v1)
✅ Loaded stage_4 prompt (v1)
✅ Loaded stage_1 heuristics (v1)
✅ Loaded stage_3 heuristics (v1)
🎉 All prompts and heuristics loaded successfully!
```

**Note:** This script is safe to run multiple times - it skips prompts that already exist.

---

### Step 2: Prepare Test Audio

Get a short audio file (MP3 format, 30-60 minutes of political debate content):

```bash
# Create test directory
mkdir -p ~/verdad_debates_storage/test

# Copy your test audio file
# Replace /path/to/your/debate.mp3 with your actual file
cp /path/to/your/debate.mp3 ~/verdad_debates_storage/test/test_debate.mp3

# Verify file exists
ls -lh ~/verdad_debates_storage/test/test_debate.mp3
```

---

### Step 3: Insert Audio File Record

```bash
# Add the audio file to the database
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
    'test/test_debate.mp3',
    'test_debate.mp3',
    10485760,
    1800,
    NOW() - INTERVAL '2 hours',
    TO_CHAR(NOW(), 'Day'),
    'Test Radio Station',
    'TEST',
    'California',
    'Los Angeles',
    'New'
) RETURNING id, file_name, status, recorded_at;
EOF
```

**Expected:** Returns UUID and shows status='New'

---

### Step 4: Start Prefect Server

Open a **separate terminal** and start Prefect:

```bash
# Terminal 1: Start Prefect server
cd /home/ramsus/Programming/political-debate-fact-checking-system
poetry run prefect server start
```

**Expected:** Server starts on `http://127.0.0.1:4200`

Keep this terminal open!

---

### Step 5: Run Stage 1 (Detection & Transcription)

In a **new terminal**, run Stage 1:

```bash
# Terminal 2: Run Stage 1
cd /home/ramsus/Programming/political-debate-fact-checking-system
poetry run python -c "
from src.processing_pipeline.stage_1 import initial_disinformation_detection
print('🚀 Starting Stage 1: Initial Disinformation Detection')
initial_disinformation_detection(audio_file_id=None, limit=1)
print('✅ Stage 1 complete!')
"
```

**What happens:**
1. Fetches audio file with status='New'
2. Uploads to Google Gemini for transcription
3. Runs disinformation detection
4. Creates `stage_1_llm_responses` record with detected snippets
5. Changes audio file status: 'New' → 'Processed'

**Expected output:**
- "Found a new audio file: ..."
- "Processing audio file..."
- "Transcription complete"
- "Detection complete"
- Status='Processed'

**Typical runtime:** 5-15 minutes (depends on audio length)

---

### Step 6: Check Stage 1 Results

```bash
# View the Stage 1 results
psql -U verdad_user -d verdad_debates -c "
SELECT 
    id,
    status,
    jsonb_array_length(detection_result->'flagged_snippets') as snippet_count
FROM stage_1_llm_responses
ORDER BY created_at DESC
LIMIT 1;
"
```

**Expected:** Shows status='Processed' and snippet count > 0

---

### Step 7: Run Stage 2 (Audio Clipping)

```bash
# Terminal 2: Run Stage 2
poetry run python -c "
from src.processing_pipeline.stage_2 import audio_clipping
print('🚀 Starting Stage 2: Audio Clipping')
audio_clipping(context_before_seconds=5, context_after_seconds=5, repeat=False)
print('✅ Stage 2 complete!')
"
```

**What happens:**
1. Fetches Stage 1 response with status='New'
2. Extracts audio clips for each flagged snippet
3. Saves clips to `~/verdad_debates_storage/snippets/`
4. Creates `snippets` records
5. Changes Stage 1 response status: 'New' → 'Processed'

**Expected output:**
- "Found stage-1 LLM response: ..."
- "Loading audio file into memory"
- "Processing snippet [uuid]..."
- "File uploaded to storage as ..."

**Typical runtime:** 1-3 minutes

---

### Step 8: Check Stage 2 Results

```bash
# View created snippets
psql -U verdad_user -d verdad_debates -c "
SELECT 
    id,
    file_path,
    duration,
    status,
    transcription IS NOT NULL as has_transcription
FROM snippets
ORDER BY created_at DESC
LIMIT 5;
"

# Verify audio clips exist
ls -lh ~/verdad_debates_storage/*/snippets/
```

**Expected:** Shows snippets with status='New' and actual .mp3 files in storage

---

### Step 9: Run Stage 3 (In-Depth Analysis)

```bash
# Terminal 2: Run Stage 3
poetry run python -c "
from src.processing_pipeline.stage_3 import in_depth_analysis
print('🚀 Starting Stage 3: In-Depth Analysis')
in_depth_analysis(snippet_ids=None, skip_review=False, repeat=False)
print('✅ Stage 3 complete!')
"
```

**What happens:**
1. Fetches snippet with status='New'
2. Downloads audio clip
3. Runs deep analysis with Google Gemini
4. Performs web searches for fact-checking
5. Saves analysis to `previous_analysis` field
6. Changes status: 'New' → 'Ready for review'

**Expected output:**
- "Found the snippet: ..."
- "Analyzing snippet..."
- "Search queries generated: ..."
- "Analysis complete"

**Typical runtime:** 2-5 minutes per snippet

---

### Step 10: Check Stage 3 Results

```bash
# View analysis results
psql -U verdad_user -d verdad_debates -c "
SELECT 
    id,
    status,
    previous_analysis->>'category' as category,
    previous_analysis->>'claim_summary' as claim
FROM snippets
WHERE previous_analysis IS NOT NULL
ORDER BY created_at DESC
LIMIT 1;
"
```

**Expected:** Shows status='Ready for review' with analysis data

---

### Step 11: Run Stage 4 (Human Review Simulation)

For testing, we'll mark the snippet as reviewed:

```bash
# Manual review: Mark as processed
psql -U verdad_user -d verdad_debates << 'EOF'
UPDATE snippets 
SET 
    status = 'Processed',
    final_review = previous_analysis
WHERE status = 'Ready for review'
RETURNING id, status;
EOF
```

**Note:** In production, Stage 4 would run a review flow. For testing, we're simulating approval.

---

### Step 12: Run Stage 5 (Generate Embeddings)

```bash
# Terminal 2: Run Stage 5
poetry run python -c "
from src.processing_pipeline.stage_5 import embedding
print('🚀 Starting Stage 5: Generate Embeddings')
embedding(repeat=False)
print('✅ Stage 5 complete!')
"
```

**What happens:**
1. Fetches snippet with status='Processed' (no embedding)
2. Generates 768-dimensional vector embedding using OpenAI
3. Stores in `snippet_embeddings` table
4. Enables similarity search

**Expected output:**
- "Generating embedding for snippet: ..."
- "Embedding saved successfully"

**Typical runtime:** < 1 minute

---

### Step 13: Verify Complete Pipeline

```bash
# Check the full pipeline status
psql -U verdad_user -d verdad_debates -c "
SELECT 
    'Audio Files' as stage,
    COUNT(*) FILTER (WHERE status = 'Processed') as processed,
    COUNT(*) as total
FROM audio_files
UNION ALL
SELECT 
    'Stage 1 Responses',
    COUNT(*) FILTER (WHERE status = 'Processed'),
    COUNT(*)
FROM stage_1_llm_responses
UNION ALL
SELECT 
    'Snippets',
    COUNT(*) FILTER (WHERE status = 'Processed'),
    COUNT(*)
FROM snippets
UNION ALL
SELECT 
    'Embeddings',
    COUNT(*),
    COUNT(*)
FROM snippet_embeddings;
"
```

**Expected output:**
```
      stage       | processed | total 
------------------+-----------+-------
 Audio Files      |         1 |     1
 Stage 1 Responses|         1 |     1
 Snippets         |         1 |     1
 Embeddings       |         1 |     1
```

---

## Automated Testing: Run All Stages Sequentially

Create a test script:

```bash
# Create test script
cat > test_pipeline.sh << 'EOF'
#!/bin/bash
set -e

echo "🚀 Testing Complete Processing Pipeline"
echo "========================================"

cd /home/ramsus/Programming/political-debate-fact-checking-system

echo ""
echo "✅ Stage 1: Initial Detection"
poetry run python -c "from src.processing_pipeline.stage_1 import initial_disinformation_detection; initial_disinformation_detection(None, 1)" 2>&1 | tail -5

echo ""
echo "✅ Stage 2: Audio Clipping"
poetry run python -c "from src.processing_pipeline.stage_2 import audio_clipping; audio_clipping(5, 5, False)" 2>&1 | tail -5

echo ""
echo "✅ Stage 3: In-Depth Analysis"
poetry run python -c "from src.processing_pipeline.stage_3 import in_depth_analysis; in_depth_analysis(None, False, False)" 2>&1 | tail -5

echo ""
echo "✅ Stage 4: Manual Review (simulated)"
psql -U verdad_user -d verdad_debates -c "UPDATE snippets SET status='Processed', final_review=previous_analysis WHERE status='Ready for review'" -q

echo ""
echo "✅ Stage 5: Generate Embeddings"
poetry run python -c "from src.processing_pipeline.stage_5 import embedding; embedding(False)" 2>&1 | tail -5

echo ""
echo "🎉 Pipeline test complete!"
echo ""
echo "📊 Results:"
psql -U verdad_user -d verdad_debates -c "SELECT 'Embeddings Created' as result, COUNT(*) as count FROM snippet_embeddings"
EOF

chmod +x test_pipeline.sh
```

Run it:
```bash
./test_pipeline.sh
```

---

## Monitoring & Debugging

### View Prefect Dashboard

Open in browser: http://127.0.0.1:4200

You'll see:
- Flow runs
- Task status
- Execution logs
- Error traces

### Check Logs

```bash
# View recent logs
poetry run prefect deployment ls
poetry run prefect flow-run ls --limit 10
```

### Reset Test Data

```bash
# Clear all test data to start fresh
psql -U verdad_user -d verdad_debates << 'EOF'
TRUNCATE snippet_embeddings CASCADE;
TRUNCATE snippets CASCADE;
TRUNCATE stage_1_llm_responses CASCADE;
TRUNCATE audio_files CASCADE;
EOF

# Remove audio files
rm -f ~/verdad_debates_storage/*/snippets/*.mp3
```

---

## Common Issues

### Issue: "No new audio files found"
**Solution:** Check audio file status:
```bash
psql -U verdad_user -d verdad_debates -c "SELECT id, status FROM audio_files;"
# Reset if needed:
psql -U verdad_user -d verdad_debates -c "UPDATE audio_files SET status='New' WHERE status='Processing';"
```

### Issue: "ImportError: No module named psycopg2"
**Solution:**
```bash
poetry install
```

### Issue: "FileNotFoundError: Audio file not found"
**Solution:** Verify file path matches database record:
```bash
# Check database path
psql -U verdad_user -d verdad_debates -c "SELECT file_path FROM audio_files WHERE status='New';"

# Check actual file
ls ~/verdad_debates_storage/test/
```

### Issue: API rate limits (Gemini/OpenAI)
**Solution:** Add delays between stages or use smaller test files.

---

## Production Deployment

Once testing is successful, deploy workers:

```bash
# Terminal 1: Prefect server
poetry run prefect server start

# Terminal 2: Stage 1 worker
poetry run python -m src.processing_pipeline.main stage_1

# Terminal 3: Stage 2 worker  
poetry run python -m src.processing_pipeline.main stage_2

# Terminal 4: Stage 3 worker
poetry run python -m src.processing_pipeline.main stage_3

# Terminal 5: Stage 5 worker
poetry run python -m src.processing_pipeline.main stage_5
```

Or use the provided scripts:
```bash
./scripts/start_prefect_server.sh
./scripts/start_processing.sh
```

---

## Success Criteria

Your system is working correctly when:
- ✅ All 5 stages complete without errors
- ✅ Snippet audio files exist in storage
- ✅ Database has records at each stage
- ✅ Embeddings are generated
- ✅ Prefect dashboard shows successful runs

**Next steps:** Upload real debate recordings and monitor the system!
