# Quick Start

Get the VERDAD recording and analysis pipeline running in under five minutes. This guide covers environment configuration and launching the processing workers.

### 1. Prerequisites

Ensure you have the following accounts and API keys available:
*   **Google AI Studio:** For Gemini Flash/Pro APIs (1.5 or 2.5, `GOOGLE_GEMINI_KEY`).
*   **OpenAI:** For Whisper ASR transcription.
*   **Supabase:** For the Postgres database and authentication.
*   **Prefect Cloud/Server:** To orchestrate the processing flows.
*   **Resend:** For email notifications (if using the server component).

### 2. Environment Configuration

Create a `.env` file in the root directory. Use the following template to configure your credentials:

```bash
# Core AI Services
GOOGLE_GEMINI_KEY=your_gemini_key
OPENAI_API_KEY=your_openai_key

# Database (Supabase)
SUPABASE_URL=your_project_url
SUPABASE_KEY=your_service_role_key

# Orchestration & Monitoring
SENTRY_DSN=your_sentry_dsn
ENABLE_PREFECT_DECORATOR=true

# Notification Services (Server only)
LIVEBLOCKS_SECRET_KEY=your_key
RESEND_API_KEY=your_key
SLACK_NOTIFICATION_EMAIL=your_slack_bridge_email
```

### 3. Pipeline Setup

The VERDAD pipeline is modular, allowing you to run specific stages as independent workers. 

#### Install Dependencies
```bash
# Python Pipeline
pip install -r requirements.txt

# Server Component (Node.js)
cd server && npm install
```

### 4. Running the Workers

VERDAD uses the `FLY_PROCESS_GROUP` environment variable to determine which stage a worker should execute. You can run these locally or deploy them to Fly.io.

#### Recording (Optional)
Choose one of two recording modes:

**Generic Recording** (web-based radio with browser automation):
```bash
export FLY_PROCESS_GROUP=generic_recording
python -m src.generic_recording
```

**Direct URL Recording** (non-web streams):
```bash
python -m src.recording
```

#### Start the Initial Detection (Stage 1)
This worker monitors the database for new audio files and performs rapid screening using Gemini.
```bash
export FLY_PROCESS_GROUP=initial_disinformation_detection
python -m src.processing_pipeline.main
```

#### Start the Audio Clipper (Stage 2)
Extracts snippets identified in Stage 1 with configurable context windows.
```bash
export FLY_PROCESS_GROUP=audio_clipping
python -m src.processing_pipeline.main
```

#### Start In-Depth Analysis (Stage 3)
Generates structured content analysis, translations, and disinformation categories.
```bash
export FLY_PROCESS_GROUP=in_depth_analysis
python -m src.processing_pipeline.main
```

#### Parallel Processing
To increase throughput, run multiple instances of the same worker:
```bash
# Terminal 1
export FLY_PROCESS_GROUP=initial_disinformation_detection
python -m src.processing_pipeline.main

# Terminal 2
export FLY_PROCESS_GROUP=initial_disinformation_detection_2
python -m src.processing_pipeline.main
```

Supported parallel variants: `initial_disinformation_detection_2`, `analysis_review_2`

### 5. Running the Backend Server

The Express server handles real-time collaboration via Liveblocks and syncs comments to Supabase.

```bash
cd server
npm run dev
```

### Pipeline Overview

| Process Group | Function | Key Model/Tool |
| :--- | :--- | :--- |
| `initial_disinformation_detection` | Flags potential disinformation in raw audio | Gemini 1.5/2.5 Flash |
| `audio_clipping` | Segments audio into snippets for review | FFmpeg/Audio Logic |
| `in_depth_analysis` | Deep dive analysis and structured metadata | Gemini 1.5/2.5 Pro |
| `analysis_review` | Final validation of the AI-generated claims | Stage 4 Executor |
| `embedding` | Vectorizes snippets for similarity search | Stage 5 Model |

### Local Testing Without Prefect

To run and test stages without Prefect orchestration (useful for local development):

```bash
export ENABLE_PREFECT_DECORATOR=false
python -m src.main
```

This disables the Prefect flow/task decorators and runs code directly. Edit `src/main.py` to test a specific snippet_id.

### Utility Commands

See [Utility Scripts](../maintenance/utility-scripts.md) for:
- Undoing Stage 1 or Stage 2 processing
- Regenerating transcripts
- Redoing detection with updated heuristics
- Managing Prefect flow runs
```
Move quick-start.md to getting-started/
```
