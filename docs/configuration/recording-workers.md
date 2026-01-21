# Recording Workers

The recording infrastructure in VERDAD is designed for 24/7 continuous monitoring of live radio streams. It utilizes Prefect for orchestration and Fly.io for scalable deployment, allowing for both broad monitoring and dedicated, station-specific resources.

**See also:** [Radio Recording System](radio-recording-system.md) for detailed documentation on generic recording with browser automation and direct URL recording.

## Overview

Recording workers are responsible for connecting to remote audio streams (AAC/MP3), capturing the audio data, and segmenting it into manageable files (typically 5–15 minutes) for the AI analysis pipeline. 

The system distinguishes between two types of worker configurations:
1.  **Generic Workers**: Handle pipeline tasks (detection, transcription, analysis) that are not tied to a specific station.
2.  **Station-Specific Workers**: Dedicated processes focused on maintaining a stable connection to a single high-priority radio stream.

## Station Configuration

Radio stations are configured in the system via the `fetch_radio_stations` utility. To add a new station to the monitoring list, the station must be defined with its source URL and metadata.

### Station Schema

Each station is defined as a dictionary within the configuration list:

| Field | Type | Description |
| :--- | :--- | :--- |
| `name` | string | The human-readable name of the station (e.g., "Radio Centro"). |
| `code` | string | A unique identifier, typically combining call sign and frequency. |
| `url` | string | The direct path to the live audio stream (AAC, MP3, or stream relay). |
| `state` | string | The geographic region or state where the station is based. |

**Example Configuration:**

```python
{
    "code": "WLEL - 94.3 FM",
    "url": "https://securenetg.com/radio/8090/radio.aac",
    "state": "Georgia",
    "name": "El Gallo",
}
```

## Running Recording Workers

Workers are deployed using Prefect's `serve` functionality. This allows the system to manage concurrency and retries automatically.

### Deployment via Process Groups

VERDAD uses the `FLY_PROCESS_GROUP` environment variable to determine which worker type an instance should initialize. This is managed in the entry point of the processing pipeline.

To start a specific worker, the environment must be configured with the appropriate group name. While analysis workers handle Stages 1–5, recording workers focus on the ingestion of the audio files that appear in the `audio_files` table.

### Local Execution

To run a worker locally for testing or a specific station, ensure your environment variables (Supabase and Gemini keys) are set, then execute the pipeline entry point:

```bash
# Example: Starting an analysis worker
export FLY_PROCESS_GROUP="initial_disinformation_detection"
python src/processing_pipeline/main.py
```

## Database Integration

When a recording worker successfully captures a segment, it interfaces with the `SupabaseClient` to register the file. This triggers the rest of the AI pipeline.

### `insert_audio_file`
Internal workers use this method to log the completion of a recording segment.

**Input Parameters:**
- `radio_station_name`: Name from configuration.
- `radio_station_code`: Unique station code.
- `location_state`: Geographic metadata.
- `recorded_at`: ISO timestamp of the recording start.
- `recording_day_of_week`: Day name (e.g., "Monday").
- `file_path`: Storage path (e.g., S3 or Supabase Storage).
- `file_size`: Size in bytes.

## Monitoring and Maintenance

### Health Checks
The recording workers report their status to Prefect. If a stream connection drops, Prefect’s retry logic (configured via `optional_task` decorators) will attempt to reconnect.

### Error Handling
If a worker encounters a persistent issue (e.g., a dead stream URL), it updates the status of the attempt in the database. 

- **Status Updates**: Workers use `set_audio_file_status` to mark segments as `processing`, `completed`, or `failed`.
- **Sentry Integration**: All workers are wrapped with Sentry SDK initialization to capture runtime exceptions and stream interruptions in real-time.

```python
# Sentry is initialized automatically on worker startup
import sentry_sdk
sentry_sdk.init(dsn=os.getenv("SENTRY_DSN"))
```
