# Stage 2: Audio Clipping

## Overview

Stage 2 of the VERDAD pipeline focuses on the automated extraction of audio segments identified during the initial screening (Stage 1). Rather than processing a full 15-minute radio broadcast, this stage isolates specific "snippets" of interest. 

To ensure that the content is analyzed accurately in later stages, the system automatically prepends and appends a configurable amount of "context" audio to each flagged detection.

## The Clipping Process

The process is orchestrated by Prefect and involves fetching detections that have been flagged by the Stage 1 LLM, calculating the appropriate time windows, and generating discrete audio files for further processing.

### Input
- **Original Audio Files**: The raw recordings (typically 5–15 minutes).
- **Stage 1 Metadata**: Specific timestamps and IDs where potential disinformation was detected.

### Output
- **Audio Snippets**: Isolated audio files containing the suspected content plus surrounding context.
- **Database Records**: Updated snippet entries in Supabase linked to the original audio file.

## Configuration and Usage

The clipping process is highly configurable to account for different radio formats and the latency of live detection.

### Audio Clipping Task
This task extracts segments based on the timestamps provided by the initial detection stage.

**Deployment Parameters:**
| Parameter | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `context_before_seconds` | `int` | `90` | The amount of audio to include *before* the flagged timestamp. |
| `context_after_seconds` | `int` | `60` | The amount of audio to include *after* the flagged timestamp. |
| `repeat` | `bool` | `True` | Whether the process should continuously check for new Stage 1 outputs. |

**Usage Example:**
```python
# Typically triggered via the Prefect deployment or CLI
# Using the FLY_PROCESS_GROUP="audio_clipping" environment variable

deployment = audio_clipping.to_deployment(
    name="Stage 2: Audio Clipping",
    concurrency_limit=100,
    parameters=dict(
        context_before_seconds=90, 
        context_after_seconds=60, 
        repeat=True
    ),
)
```

### Undo Audio Clipping
If clipping needs to be re-run (e.g., if context windows were insufficient or metadata was corrupted), the `undo_audio_clipping` task allows for a clean rollback of specific responses.

**Input:**
- `stage_1_llm_response_ids`: A list of IDs to revert, removing their associated snippets and resetting their status.

## Management via Prefect

Stage 2 is designed to run as a continuous worker. In the production environment (Fly.io), it is managed via the `FLY_PROCESS_GROUP` environment variable.

To start the clipping worker:
```bash
export FLY_PROCESS_GROUP="audio_clipping"
python src/processing_pipeline/main.py
```

## Internal Roles
While primarily automated, the internal logic handles:
1. **Status Management**: Moving records from "detected" to "clipped" status.
2. **Metadata Association**: Ensuring the snippet remains tied to its original station code, location, and recording time.
3. **Concurrency Control**: Managing up to 100 simultaneous clipping tasks to handle high volumes of radio traffic.
