# Stage 1: Initial Disinformation Detection - Deep Dive

This document provides a comprehensive analysis of how Stage 1 works, including architecture, prompts, testing, and customization.

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture & Flow](#architecture--flow)
3. [Prompt System](#prompt-system)
4. [Testing Stage 1](#testing-stage-1)
5. [Modifying Prompts](#modifying-prompts)
6. [Debugging & Troubleshooting](#debugging--troubleshooting)
7. [Performance Optimization](#performance-optimization)
8. [Real-World Examples](#real-world-examples)

---

## Overview

### Purpose

Stage 1 is the entry point of the processing pipeline. It performs two critical tasks:

1. **Transcription**: Converts audio to timestamped text using Google Gemini's multimodal capabilities
2. **Initial Detection**: Analyzes the transcript to identify potential disinformation snippets

### Key Characteristics

- **Model**: Uses Google Gemini 2.5 Flash (configurable)
- **Input**: MP3 audio file from local storage
- **Output**: 
  - Timestamped transcription (stored in database)
  - List of flagged snippets with metadata (timestamps, categories, claims)
- **Duration**: 5-15 minutes for 30-60 minute audio files
- **Status Flow**: `audio_files.status: New → Processing → Processed/Error`

---

## Architecture & Flow

### High-Level Flow Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                         STAGE 1 WORKFLOW                         │
└─────────────────────────────────────────────────────────────────┘

1. Fetch Audio File
   ├─ Query: SELECT audio_files WHERE status='New'
   ├─ Lock: FOR UPDATE SKIP LOCKED (prevents race conditions)
   └─ Update: status='Processing'

2. Download Audio
   ├─ Path: ~/verdad_debates_storage/{file_path}
   └─ Validate: File exists

3. Load Prompts
   ├─ Transcription Prompt: 'gemini_timestamped_transcription'
   └─ Detection Prompt: 'stage_1'

4. Transcribe Audio (Gemini API)
   ├─ Upload MP3 to Gemini
   ├─ Apply transcription prompt
   └─ Receive: Timestamped text

5. Detect Disinformation (Gemini API)
   ├─ Input: Transcription + metadata
   ├─ Apply detection prompt + schema
   └─ Receive: JSON with flagged_snippets[]

6. Save Results
   ├─ Insert: stage_1_llm_responses
   │   ├─ timestamped_transcription (JSONB)
   │   └─ detection_result (JSONB)
   ├─ Update: audio_files.status='Processed'
   └─ Delete: Local audio file (cleanup)

7. Ready for Stage 2
   └─ stage_1_llm_responses.status='New' triggers Stage 2
```

### Code Components

**File**: `src/processing_pipeline/stage_1.py`

**Key Functions**:

1. `initial_disinformation_detection()` - Main Prefect flow
2. `fetch_a_new_audio_file_from_supabase()` - Gets audio file with reservation
3. `download_audio_file_from_s3()` - Downloads from local storage
4. `get_audio_file_metadata()` - Extracts metadata for context
5. `transcribe_audio_file_with_timestamp_with_gemini()` - Transcription task
6. `disinformation_detection_with_gemini()` - Detection task
7. `insert_stage_1_llm_response()` - Saves results to DB

**Classes**:

1. `GeminiTimestampTranscriptionGenerator` - Handles Gemini file upload and transcription
2. `Stage1Executor` - Handles Gemini detection with structured output

---

## Prompt System

### How Prompts Are Stored

Prompts are stored in the `prompt_versions` table with the following structure:

```sql
CREATE TABLE prompt_versions (
    id UUID PRIMARY KEY,
    stage TEXT NOT NULL,              -- e.g., 'stage_1', 'gemini_timestamped_transcription'
    version_number INTEGER NOT NULL,
    llm_model TEXT NOT NULL,          -- e.g., 'gemini-2.5-flash'
    prompt_text TEXT NOT NULL,        -- The main prompt
    system_instruction TEXT,          -- System-level instructions
    output_schema JSONB,              -- Expected JSON output structure
    is_active BOOLEAN DEFAULT FALSE,  -- Only one active version per stage
    change_explanation TEXT,
    created_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ
);
```

### Active Prompts in Stage 1

#### 1. Transcription Prompt

**Stage**: `gemini_timestamped_transcription`  
**Source File**: `prompts/Gemini_timestamped_transcription_generation_prompt.md`  
**Purpose**: Instructs Gemini how to transcribe audio with timestamps

**Key Instructions**:
- Transcribe with phrase-level timestamps (format: `[MM:SS]`)
- Capture dialects, accents, and colloquialisms
- Note non-speech elements: `[music]`, `[inaudible]`, `[noise]`
- Insert timestamps at natural pauses (max 15 seconds between)
- Maintain cultural sensitivity

**Example Output**:
```
[00:00] Hello, how are you? [background music]
[00:05] I'm fine, thank you. [child laughing]
[00:10] Let's discuss the election results...
```

**Schema**: Defined in `prompts/Timestamped_transcription_generation_output_schema.json`

```json
{
  "type": "object",
  "properties": {
    "timestamped_transcription": {
      "type": "string",
      "description": "Full transcription with [MM:SS] timestamps"
    }
  }
}
```

#### 2. Detection Prompt

**Stage**: `stage_1`  
**Source Files**:
- Prompt: `prompts/Stage_1_detection_prompt.md`
- System Instruction: `prompts/Stage_1_system_instruction.md`
- Heuristics: `prompts/Stage_1_heuristics.md`
- Output Schema: `prompts/Stage_1_output_schema.json`

**Purpose**: Analyzes transcription for potential disinformation

**What It Detects**:
1. **False Statistics** - Incorrect numbers, percentages, data
2. **Misleading Context** - Facts presented misleadingly
3. **Conspiracy Theories** - Unfounded claims
4. **Deepfakes/Manipulated Media** - References to altered content
5. **Health Misinformation** - False medical/scientific claims
6. **Election Misinformation** - False voting/election claims
7. **Historical Revisionism** - Distorted historical facts
8. **Financial Scams** - Fraudulent schemes
9. **Identity Theft** - Phishing, impersonation
10. **Emotional Manipulation** - Fear-mongering, propaganda

**Detection Criteria** (from Stage_1_heuristics.md):
- Must be a **factual claim** (not opinion)
- Must be **verifiable** through evidence
- Must have **potential harm** if believed
- Must have **sufficient context** to fact-check
- Must **not be satire/parody**

**Example Output Structure**:
```json
{
  "flagged_snippets": [
    {
      "uuid": "550e8400-e29b-41d4-a716-446655440000",
      "start_timestamp": "05:23",
      "end_timestamp": "05:45",
      "category": "false_statistics",
      "claim_summary": "Claims unemployment rate is 15% when official data shows 4.2%",
      "transcription": "[05:23] The unemployment rate has skyrocketed to 15 percent...",
      "context": "Speaker discussing economic policy during debate",
      "confidence_score": 0.85,
      "potential_harm": "high",
      "reason_for_flagging": "Significantly contradicts official employment data"
    }
  ]
}
```

**Schema Fields**:
- `uuid`: Unique identifier for snippet
- `start_timestamp` / `end_timestamp`: Temporal boundaries in MM:SS format
- `category`: One of 10 disinformation types
- `claim_summary`: Brief description of the false claim
- `transcription`: Exact text from transcript
- `context`: Background information
- `confidence_score`: 0.0-1.0 confidence in detection
- `potential_harm`: `low`, `medium`, `high`
- `reason_for_flagging`: Explanation of why it was flagged

### How Prompts Are Retrieved

**Code**: `src/processing_pipeline/postgres_client.py`

```python
def get_active_prompt(self, stage: str):
    """Get active prompt version for a stage."""
    result = self._execute(
        "SELECT * FROM prompt_versions WHERE stage = %s AND is_active = TRUE",
        (stage,),
        fetch_one=True
    )
    if not result:
        raise ValueError(f"No active prompt version found for stage: {stage}")
    return result
```

**Usage in Stage 1**:
```python
# Load prompts
transcription_prompt_version = supabase_client.get_active_prompt(
    PromptStage.GEMINI_TIMESTAMPED_TRANSCRIPTION
)
detection_prompt_version = supabase_client.get_active_prompt(
    PromptStage.STAGE_1
)

# Use in Gemini calls
GeminiTimestampTranscriptionGenerator.run(
    audio_file=audio_file,
    gemini_key=gemini_key,
    model_name=model_name,
    user_prompt=transcription_prompt_version["prompt_text"],
)

Stage1Executor.run(
    gemini_key=gemini_key,
    model_name=model_name,
    timestamped_transcription=transcription,
    metadata=metadata,
    prompt_version=detection_prompt_version,
)
```

### Prompt Composition

When calling Gemini for detection, the final prompt is composed as:

```python
user_prompt = (
    f"{prompt_version['prompt_text']}\n\n"
    f"Here is the metadata of the transcription:\n\n{json.dumps(metadata, indent=2)}\n\n"
    f"Here is the timestamped transcription:\n\n{timestamped_transcription}"
)
```

**Metadata Included**:
```json
{
  "radio_station_name": "Test Radio Station",
  "radio_station_code": "TEST",
  "location": {
    "state": "California",
    "city": "Los Angeles"
  },
  "recorded_at": "January 23, 2026 6:15 AM",
  "recording_day_of_week": "Friday",
  "time_zone": "UTC"
}
```

---

## Testing Stage 1

### Quick Test: End-to-End

```bash
# 1. Ensure environment is configured
cat .env | grep -E "(DATABASE_URL|GOOGLE_GEMINI_KEY|STORAGE_PATH)"

# 2. Load prompts (first time only)
poetry run python scripts/load_prompts.py

# 3. Insert test audio file record
psql -U verdad_user -d verdad_debates << 'EOF'
INSERT INTO audio_files (
    file_path, file_name, file_size, duration,
    recorded_at, recording_day_of_week,
    radio_station_name, radio_station_code,
    location_state, location_city, status
) VALUES (
    'test/political_debate.mp3', 'political_debate.mp3',
    10485760, 1800, NOW(), 'Friday',
    'Test Station', 'TEST', 'CA', 'LA', 'New'
) RETURNING id, file_name, status;
EOF

# 4. Copy audio file to storage
mkdir -p ~/verdad_debates_storage/test
cp /path/to/political_debate.mp3 ~/verdad_debates_storage/test/

# 5. Run Stage 1
poetry run python -c "
from src.processing_pipeline.stage_1 import initial_disinformation_detection
initial_disinformation_detection(audio_file_id=None, limit=1)
"

# 6. Check results
psql -U verdad_user -d verdad_debates -c "
SELECT 
    af.file_name,
    af.status as audio_status,
    s1.status as llm_status,
    jsonb_array_length(s1.detection_result->'flagged_snippets') as snippets_found
FROM audio_files af
LEFT JOIN stage_1_llm_responses s1 ON s1.audio_file = af.id
ORDER BY af.created_at DESC
LIMIT 1;
"
```

### Testing Individual Components

#### Test 1: Database Connection
```bash
poetry run python -c "
from src.processing_pipeline.postgres_client import PostgresClient
db = PostgresClient()
print('✅ Database connected')
db.close()
"
```

#### Test 2: Prompt Retrieval
```bash
poetry run python -c "
from src.processing_pipeline.postgres_client import PostgresClient
from src.processing_pipeline.constants import PromptStage

db = PostgresClient()
prompt = db.get_active_prompt(PromptStage.STAGE_1)
print(f'✅ Prompt loaded: {prompt[\"stage\"]} v{prompt[\"version_number\"]}')
print(f'   Model: {prompt[\"llm_model\"]}')
print(f'   Prompt length: {len(prompt[\"prompt_text\"])} chars')
print(f'   Has system instruction: {prompt[\"system_instruction\"] is not None}')
print(f'   Has output schema: {prompt[\"output_schema\"] is not None}')
db.close()
"
```

#### Test 3: Storage Access
```bash
poetry run python -c "
from src.processing_pipeline.local_storage import LocalStorage
storage = LocalStorage()
print(f'✅ Storage initialized at: {storage.base_path}')

# List files
import os
audio_dir = os.path.join(storage.base_path, 'test')
if os.path.exists(audio_dir):
    files = os.listdir(audio_dir)
    print(f'   Test files found: {len(files)}')
    for f in files:
        print(f'   - {f}')
else:
    print('   ⚠️  Test directory not found')
"
```

#### Test 4: Gemini API Connection
```bash
poetry run python -c "
import os
from dotenv import load_dotenv
from google import genai

load_dotenv()
gemini_key = os.getenv('GOOGLE_GEMINI_KEY')

if not gemini_key:
    print('❌ GOOGLE_GEMINI_KEY not set')
else:
    client = genai.Client(api_key=gemini_key)
    models = client.models.list()
    print('✅ Gemini API connected')
    print('   Available models:')
    for model in list(models)[:5]:
        print(f'   - {model.name}')
"
```

### Testing with Different Audio Content

To properly test detection, use audio with varying content:

**1. Clean Political Debate** (baseline)
- Expected: Some snippets flagged
- Audio: Actual political debate with factual claims
- File size: 30-60 minutes

**2. Religious/Non-Political Content** (negative test)
- Expected: Zero snippets flagged
- Audio: Church service, music, non-political talk radio
- Result: System correctly identifies no political content

**3. Obvious Disinformation** (positive test)
- Expected: High number of snippets flagged
- Audio: Conspiracy theories, false statistics
- Result: System catches clear misinformation

**4. Edge Cases**
- Mixed language audio
- Poor audio quality
- Background noise
- Overlapping speakers

### Performance Benchmarks

Expected processing times for Stage 1:

| Audio Length | Transcription | Detection | Total | Gemini Cost |
|-------------|---------------|-----------|-------|-------------|
| 10 minutes  | 1-2 min       | 30-60 sec | ~2 min | $0.05 |
| 30 minutes  | 3-5 min       | 1-2 min   | ~5 min | $0.15 |
| 60 minutes  | 6-10 min      | 2-3 min   | ~10 min | $0.30 |

*Costs are approximate using Gemini 2.5 Flash pricing*

---

## Modifying Prompts

### Method 1: Update Existing Prompt Version (Quick Changes)

For minor tweaks without version tracking:

```bash
psql -U verdad_user -d verdad_debates << 'EOF'
UPDATE prompt_versions 
SET 
    prompt_text = 'Your updated prompt text here...',
    updated_at = NOW()
WHERE stage = 'stage_1' AND is_active = TRUE;
EOF
```

**When to use**: Quick experiments, typo fixes, minor wording changes

### Method 2: Create New Prompt Version (Recommended)

For significant changes with version history:

```bash
psql -U verdad_user -d verdad_debates << 'EOF'
-- Deactivate current version
UPDATE prompt_versions 
SET is_active = FALSE 
WHERE stage = 'stage_1' AND is_active = TRUE;

-- Insert new version
INSERT INTO prompt_versions (
    stage,
    version_number,
    llm_model,
    prompt_text,
    system_instruction,
    output_schema,
    is_active,
    change_explanation
) 
SELECT 
    stage,
    MAX(version_number) + 1,
    'gemini-2.5-flash',
    'Your new prompt text...',
    system_instruction,  -- Keep same or update
    output_schema,        -- Keep same or update
    TRUE,
    'Explanation of what changed and why'
FROM prompt_versions 
WHERE stage = 'stage_1'
GROUP BY stage, system_instruction, output_schema;
EOF
```

**When to use**: Production changes, A/B testing, significant prompt engineering

### Method 3: Update from Source Files

Edit the markdown files in `prompts/` directory, then reload:

```bash
# 1. Edit prompt files
vim prompts/Stage_1_detection_prompt.md
vim prompts/Stage_1_system_instruction.md
vim prompts/Stage_1_heuristics.md

# 2. Reload into database
poetry run python << 'EOF'
from src.processing_pipeline.postgres_client import PostgresClient
from pathlib import Path
import json

db = PostgresClient()
prompts_dir = Path('prompts')

# Deactivate current
db._execute(
    "UPDATE prompt_versions SET is_active = FALSE WHERE stage = 'stage_1' AND is_active = TRUE"
)

# Load from files
prompt_text = (prompts_dir / 'Stage_1_detection_prompt.md').read_text()
system_instruction = (prompts_dir / 'Stage_1_system_instruction.md').read_text()
output_schema = json.loads((prompts_dir / 'Stage_1_output_schema.json').read_text())

# Insert new version
db._execute("""
    INSERT INTO prompt_versions 
    (stage, version_number, llm_model, prompt_text, system_instruction, 
     output_schema, is_active, change_explanation)
    SELECT 'stage_1', COALESCE(MAX(version_number), 0) + 1, 'gemini-2.5-flash',
           %s, %s, %s, TRUE, 'Updated from source files'
    FROM prompt_versions WHERE stage = 'stage_1'
""", (prompt_text, system_instruction, json.dumps(output_schema)))

print('✅ Prompt updated from source files')
db.close()
EOF
```

### Testing Prompt Changes

**A/B Testing Framework**:

```python
# Test two prompt versions side by side
import json
from src.processing_pipeline.stage_1 import Stage1Executor
from src.processing_pipeline.postgres_client import PostgresClient

db = PostgresClient()

# Get both versions
v1 = db._execute(
    "SELECT * FROM prompt_versions WHERE stage = 'stage_1' AND version_number = 1",
    fetch_one=True
)
v2 = db._execute(
    "SELECT * FROM prompt_versions WHERE stage = 'stage_1' AND version_number = 2",
    fetch_one=True
)

# Test with same transcription
test_transcription = "[00:00] The unemployment rate is 15 percent..."
metadata = {"recorded_at": "2026-01-23", ...}

result_v1 = Stage1Executor.run(
    gemini_key=os.getenv("GOOGLE_GEMINI_KEY"),
    model_name="gemini-2.5-flash",
    timestamped_transcription=test_transcription,
    metadata=metadata,
    prompt_version=v1
)

result_v2 = Stage1Executor.run(
    gemini_key=os.getenv("GOOGLE_GEMINI_KEY"),
    model_name="gemini-2.5-flash",
    timestamped_transcription=test_transcription,
    metadata=metadata,
    prompt_version=v2
)

print(f"Version 1: {len(result_v1['flagged_snippets'])} snippets")
print(f"Version 2: {len(result_v2['flagged_snippets'])} snippets")
```

### Prompt Engineering Tips

**For Better Detection**:

1. **Be Specific About Context**: Include examples of what constitutes disinformation in your domain
2. **Define Thresholds**: Specify when to flag vs. when to skip borderline cases
3. **Include Edge Cases**: "Do not flag satire, comedy, or hypothetical scenarios"
4. **Structured Reasoning**: Ask for step-by-step analysis before final decision
5. **Confidence Scores**: Request self-assessment of detection certainty

**Example Improvement**:

Before:
```
Identify any false claims in the transcript.
```

After:
```
Analyze the transcript for factual claims that can be verified. For each claim:
1. Determine if it is a factual statement (not opinion/speculation)
2. Assess if it contradicts established evidence
3. Evaluate the potential harm if believed
4. Assign confidence score (0.0-1.0)

Only flag claims with:
- Confidence > 0.7
- Clear factual contradiction
- Medium or high potential harm

Do NOT flag:
- Opinions or predictions
- Satire or humor
- Hypothetical scenarios
- Ambiguous statements without context
```

---

## Debugging & Troubleshooting

### Common Issues

#### Issue 1: No Snippets Detected (Empty Results)

**Symptoms**:
```json
{
  "flagged_snippets": []
}
```

**Possible Causes**:

1. **Audio doesn't contain political/factual claims**
   ```bash
   # Check transcription
   psql -U verdad_user -d verdad_debates -c "
   SELECT LEFT(timestamped_transcription::text, 500) 
   FROM stage_1_llm_responses 
   ORDER BY created_at DESC LIMIT 1;
   "
   ```
   Solution: Use audio with actual political debate content

2. **Detection prompt too strict**
   ```bash
   # Review current prompt
   psql -U verdad_user -d verdad_debates -c "
   SELECT prompt_text, system_instruction 
   FROM prompt_versions 
   WHERE stage = 'stage_1' AND is_active = TRUE;
   "
   ```
   Solution: Adjust confidence thresholds or detection criteria

3. **Output schema mismatch**
   ```bash
   # Check schema
   psql -U verdad_user -d verdad_debates -c "
   SELECT output_schema 
   FROM prompt_versions 
   WHERE stage = 'stage_1' AND is_active = TRUE;
   "
   ```
   Solution: Ensure schema matches prompt expectations

#### Issue 2: Transcription Quality Poor

**Symptoms**: Garbled text, missing words, incorrect timestamps

**Solutions**:

1. **Audio quality**: Ensure clear audio, minimal background noise
2. **Format**: Use MP3 format, 44.1kHz sample rate recommended
3. **Length**: Gemini works best with <60 minute files
4. **Prompt tuning**: Adjust transcription prompt for specific accents/dialects

#### Issue 3: API Rate Limits

**Symptoms**:
```
ERROR: 429 Rate Limit Exceeded
```

**Solutions**:

1. **Add delays between calls**:
   ```python
   import time
   time.sleep(2)  # 2 second delay
   ```

2. **Use quota management**:
   ```python
   # Track API usage
   GEMINI_DAILY_QUOTA = 1500  # requests per day
   requests_made = 0
   ```

3. **Switch to paid tier**: Gemini Flash has higher limits on paid plans

#### Issue 4: Database Connection Errors

**Symptoms**:
```
psycopg2.OperationalError: could not connect to server
```

**Debug Steps**:

```bash
# 1. Check PostgreSQL is running
sudo systemctl status postgresql

# 2. Test connection
psql -U verdad_user -d verdad_debates -c "SELECT 1;"

# 3. Check DATABASE_URL
echo $DATABASE_URL

# 4. Verify .env file
cat .env | grep DATABASE_URL
```

### Enable Debug Logging

Add to your code:

```python
import logging
logging.basicConfig(level=logging.DEBUG)

# Or for Prefect
from prefect import get_run_logger

@flow
def initial_disinformation_detection():
    logger = get_run_logger()
    logger.debug("Starting Stage 1...")
    logger.debug(f"Prompt version: {prompt_version['version_number']}")
    logger.debug(f"Transcription length: {len(transcription)}")
```

### Monitoring Stage 1 in Production

**Database Queries for Health Monitoring**:

```sql
-- Processing backlog
SELECT 
    COUNT(*) FILTER (WHERE status = 'New') as pending,
    COUNT(*) FILTER (WHERE status = 'Processing') as in_progress,
    COUNT(*) FILTER (WHERE status = 'Processed') as completed,
    COUNT(*) FILTER (WHERE status = 'Error') as failed
FROM audio_files;

-- Average processing time
SELECT 
    AVG(EXTRACT(EPOCH FROM (updated_at - created_at))) / 60 as avg_minutes
FROM audio_files 
WHERE status = 'Processed' 
AND created_at > NOW() - INTERVAL '24 hours';

-- Detection rate
SELECT 
    AVG(jsonb_array_length(detection_result->'flagged_snippets')) as avg_snippets_per_audio
FROM stage_1_llm_responses
WHERE status = 'Processed';

-- Error rate
SELECT 
    COUNT(*) FILTER (WHERE status = 'Error') * 100.0 / COUNT(*) as error_rate_pct
FROM audio_files 
WHERE created_at > NOW() - INTERVAL '7 days';
```

---

## Performance Optimization

### 1. Parallel Processing

Run multiple Stage 1 workers:

```bash
# Terminal 1
poetry run python -c "
from src.processing_pipeline.stage_1 import initial_disinformation_detection
while True:
    initial_disinformation_detection(audio_file_id=None, limit=1)
"

# Terminal 2
poetry run python -c "
from src.processing_pipeline.stage_1 import initial_disinformation_detection
while True:
    initial_disinformation_detection(audio_file_id=None, limit=1)
"
```

The `FOR UPDATE SKIP LOCKED` pattern prevents conflicts.

### 2. Batch Processing

Process multiple files in one run:

```python
# Increase limit
initial_disinformation_detection(audio_file_id=None, limit=10)
```

### 3. Model Selection

Trade speed vs. quality:

```python
# Faster, cheaper (default)
model=GeminiModel.GEMINI_2_5_FLASH

# Higher quality, slower
model=GeminiModel.GEMINI_2_5_PRO
```

### 4. Prompt Optimization

Reduce token usage:

- Use concise instructions
- Minimize example length
- Remove redundant context
- Use bullet points over paragraphs

---

## Real-World Examples

### Example 1: Successful Detection

**Input Audio**: 2020 Presidential Debate excerpt

**Transcription** (excerpt):
```
[15:23] The unemployment rate dropped to 3.5%, the lowest in 50 years.
[15:30] We've created more jobs in the last two years than any administration in history.
[15:38] The stock market has reached record highs, benefiting millions of Americans.
```

**Detection Result**:
```json
{
  "flagged_snippets": [
    {
      "uuid": "a1b2c3...",
      "start_timestamp": "15:30",
      "end_timestamp": "15:38",
      "category": "false_statistics",
      "claim_summary": "Claims job creation record contradicts BLS historical data",
      "transcription": "[15:30] We've created more jobs...",
      "context": "Presidential debate discussing economic record",
      "confidence_score": 0.82,
      "potential_harm": "medium",
      "reason_for_flagging": "Exaggerates job creation numbers compared to official statistics"
    }
  ]
}
```

### Example 2: False Positive (Should Not Be Flagged)

**Input**: Comedy podcast

**Transcription**:
```
[05:12] [laughter] And then I told him, "The earth is flat and vaccines cause autism!"
[05:18] [more laughter] Like, who even believes that stuff?
```

**Expected Result**: Empty (satire/comedy)

**If Flagged**: Prompt needs better context understanding

**Fix**: Add to system instruction:
```
Ignore clearly satirical or comedic content. Indicators include:
- Laughter or humor cues
- Exaggerated absurdity
- Clear mocking tone
- Self-aware irony
```

### Example 3: Edge Case - Ambiguous Context

**Input**: News analysis

**Transcription**:
```
[10:15] Some people say the election was stolen.
[10:20] Let's examine what the evidence actually shows.
```

**Challenge**: Mentions false claim but doesn't endorse it

**Expected**: Not flagged (reporter quoting others)

**Detection Strategy**:
- Distinguish between direct claims vs. reported speech
- Look for attribution phrases: "some say", "according to", "claims that"
- Consider speaker role (journalist vs. politician)

---

## Next Steps

After mastering Stage 1:

1. **Stage 2**: Learn how flagged snippets are extracted as audio clips
2. **Stage 3**: Understand in-depth analysis with web search integration
3. **Prompt Optimization**: Experiment with different detection strategies
4. **Quality Metrics**: Build evaluation framework for detection accuracy

---

## Additional Resources

- **Gemini API Documentation**: https://ai.google.dev/
- **Prompt Engineering Guide**: https://www.promptingguide.ai/
- **Fact-Checking Best Practices**: https://www.poynter.org/ifcn/
- **Prefect Documentation**: https://docs.prefect.io/

---

## Contributing

To improve Stage 1 detection:

1. Submit prompt improvements via pull request
2. Report detection issues with audio samples
3. Share evaluation results from testing
4. Propose new disinformation categories

---

**Document Version**: 1.0  
**Last Updated**: January 23, 2026  
**Author**: AI Assistant  
**License**: MIT
