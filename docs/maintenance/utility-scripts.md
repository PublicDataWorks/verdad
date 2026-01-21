# Utility Scripts

VERDAD includes several utility scripts for managing processing flows and administrative tasks.

## Prompt Import Script

**Location:** `src/scripts/import_prompts_to_db.py`

Manages prompt versions in the database, enabling versioning and rollback capabilities.

See [Prompt Management and Versioning](../configuration/prompt-management-advanced.md) for detailed usage.

## Flow Management Scripts

### Cancel All Flows

**Location:** `src/scripts/cancel_all_flows.py`

Cancels all currently running Prefect flows.

```bash
python src/scripts/cancel_all_flows.py
```

**Use Cases:**
- Emergency stop of all processing
- Clean shutdown before deployment
- Clearing stuck flows

### Delete Flow Runs

**Location:** `src/scripts/delete_flow_runs.py`

Deletes Prefect flow run history.

```bash
python src/scripts/delete_flow_runs.py [options]
```

**Use Cases:**
- Cleanup of old flow runs to reduce database size
- Removing runs with sensitive data
- Archival before backup

## Undo Operations

VERDAD includes "undo" flows to revert processing steps:

### Stage 1 Undo

```bash
export FLY_PROCESS_GROUP=undo_disinformation_detection
python src/processing_pipeline/main.py
```

**Parameters:** `audio_file_ids` (list of audio file IDs to revert)

Reverts Stage 1 detection and resets audio file status to `New`, clearing:
- Flagged timestamps
- Initial detection results
- Transcriptions

### Stage 2 Undo

```bash
export FLY_PROCESS_GROUP=undo_audio_clipping
python src/processing_pipeline/main.py
```

**Parameters:** `stage_1_llm_response_ids` (list of Stage 1 response IDs to revert)

Removes clipped audio files and resets snippet status, clearing audio clips and metadata.

## Regeneration Operations

### Regenerate Timestamped Transcript

```bash
export FLY_PROCESS_GROUP=regenerate_timestamped_transcript
python src/processing_pipeline/main.py
```

**Parameters:** `stage_1_llm_response_ids` (list of Stage 1 response IDs)

Re-runs transcription on existing Stage 1 detections. Useful for:
- Testing new transcription methods
- Updating to higher-quality models
- Fixing transcription errors

### Redo Main Detection

```bash
export FLY_PROCESS_GROUP=redo_main_detection
python src/processing_pipeline/main.py
```

**Parameters:** `stage_1_llm_response_ids` (list of Stage 1 response IDs)

Re-runs the Gemini detection heuristics on existing audio files. Use after:
- Updating detection prompts
- Refining heuristics based on feedback
- Changing safety settings

## Parallel Processing

Multiple instances of the same process group can run in parallel for higher throughput:

```bash
# Instance 1
export FLY_PROCESS_GROUP=initial_disinformation_detection
python src/processing_pipeline/main.py

# Instance 2 (in another terminal)
export FLY_PROCESS_GROUP=initial_disinformation_detection_2
python src/processing_pipeline/main.py
```

**Supported Parallel Variants:**
- `initial_disinformation_detection` / `initial_disinformation_detection_2`
- `analysis_review` / `analysis_review_2`

This allows horizontal scaling on Fly.io or other orchestration platforms.

## Testing Environment

To run scripts and tests without Prefect orchestration:

```bash
export ENABLE_PREFECT_DECORATOR=false
python src/main.py
```

This disables the Prefect flow/task decorators, allowing direct Python execution for debugging and testing.
