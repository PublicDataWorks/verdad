# Radio Station Adapters

Radio station adapters are modular components for capturing audio from specific radio stations via web-based streams.

**See also:** [Radio Recording System](radio-recording-system.md) for comprehensive documentation on radio station adapters, including how to add new stations.

Radio station adapters are the entry point of the VERDAD pipeline. They provide the necessary configuration and connection logic to capture live audio streams from various radio stations, primarily focusing on Spanish-language broadcasts across the United States.

## Overview

The system uses a registry-based approach to manage station adapters. Each adapter defines the stream source, geographic metadata, and identification codes used throughout the processing pipeline (transcription, analysis, and database storage).

The core of the adapter system is located in `src/utils.py`, which provides the `fetch_radio_stations()` function used by the recording orchestration layer.

## Station Configuration

Each station is defined as a structured dictionary. This metadata ensures that every audio clip processed by the AI stages is correctly attributed to its source station and region.

### Metadata Schema

| Field | Type | Description |
| :--- | :--- | :--- |
| `name` | `string` | The common name or branding of the station (e.g., "El Gallo"). |
| `code` | `string` | The unique identifier, usually combining call signs and frequency. |
| `url` | `string` | The direct URL to the live AAC or MP3 audio stream. |
| `state` | `string` | The US state or region where the station is based. |

### Usage Example

To retrieve the list of active stations for the recording pipeline:

```python
from utils import fetch_radio_stations

stations = fetch_radio_stations()

for station in stations:
    print(f"Recording {station['name']} from {station['url']}")
```

## Adding a New Station

To add a new station to the VERDAD monitoring system, append a new configuration object to the list in `src/utils.py`. 

```python
{
    "code": "CALL-FM - 100.1 FM",
    "url": "https://stream-url.com/live.aac",
    "state": "California",
    "name": "Radio Example",
}
```

**Requirements for New Streams:**
*   **Direct Access:** The URL must be a direct link to an audio stream (AAC, MP3, or similar), not a link to a web player.
*   **Consistency:** The `code` must be unique to prevent collisions in the database.

## Recording Orchestration

The recording pipeline uses these adapters to initiate continuous audio capture. The process is handled by Prefect and typically follows this lifecycle:

1.  **Station Discovery:** The recording worker calls `fetch_radio_stations()`.
2.  **Stream Connection:** The system connects to the provided `url`.
3.  **Audio Chunking:** The live stream is captured and divided into manageable files (typically 5–15 minutes).
4.  **Metadata Attachment:** The station's `name`, `code`, and `state` are packaged with the audio file.
5.  **Database Registration:** The `SupabaseClient.insert_audio_file()` method (found in `src/processing_pipeline/supabase_utils.py`) creates a record in the `audio_files` table, marking it as ready for **Stage 1: Initial Disinformation Detection**.

## Interface for Stage 1

When audio files are registered, they carry the adapter's metadata. This allows the Gemini LLM and Whisper ASR models to receive cultural and geographic context, which is critical for nuanced disinformation analysis.

```python
# Example of metadata passed to the AI pipeline
metadata = {
    "radio_station_name": "Radio Centro",
    "radio_station_code": "WLCH - 91.3 FM",
    "location_state": "Pennsylvania"
}
```

## Internal Recording Class

While the individual station configurations are public, the underlying recording mechanism is an internal utility that handles:
*   Network resilience (automatic reconnection if a stream drops).
*   Buffer management to prevent data loss during chunk transitions.
*   File formatting and validation before storage.
