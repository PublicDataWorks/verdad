# Fly.io Configuration

## Fly.io Deployment Architecture

VERDAD is designed to run as a distributed system on Fly.io. The architecture leverages Fly.io **Processes** to run multiple specialized workers from a single codebase. This allows for independent scaling of different stages in the AI pipeline (e.g., scaling Stage 1 detection separately from Stage 3 in-depth analysis).

### Process Groups

The entry point for the processing pipeline (`src/processing_pipeline/main.py`) uses the `FLY_PROCESS_GROUP` environment variable to determine which Prefect deployment to initialize. 

When configuring your `fly.toml`, define the following processes to match the pipeline stages:

| Process Group Name | Description |
| :--- | :--- |
| `initial_disinformation_detection` | Runs Stage 1: Initial screening using Gemini (1.5 or 2.5 Flash). |
| `audio_clipping` | Runs Stage 2: Extracts segments from raw audio files. |
| `in_depth_analysis` | Runs Stage 3: Detailed multi-lingual analysis and categorization. |
| `analysis_review` | Runs Stage 4: Final AI review and validation. |
| `embedding` | Runs Stage 5: Generates vector embeddings for search and similarity. |
| `regenerate_timestamped_transcript`| Utility process for re-processing transcripts. |

---

## Configuration (`fly.toml`)

To manage the distributed pipeline, your `fly.toml` should define a `[processes]` section. This allows you to assign specific resources and scaling rules to each stage of the VERDAD pipeline.

### Example Process Configuration

```toml
[processes]
  stage_1 = "python src/processing_pipeline/main.py"
  stage_2 = "python src/processing_pipeline/main.py"
  stage_3 = "python src/processing_pipeline/main.py"

[env]
  # Default environment variables
  ENABLE_PREFECT_DECORATOR = "true"

[[services]]
  # Configuration for the primary API or dashboard if applicable
  processes = ["stage_1"] # Assign specific services to processes
```

To ensure the correct stage runs in the correct process, you must set the `FLY_PROCESS_GROUP` for each specific machine or process group:

```bash
# Example: Setting the process group for a worker via Fly CLI
fly machine update --metadata FLY_PROCESS_GROUP=initial_disinformation_detection <machine-id>
```

---

## Required Environment Variables

The following secrets and environment variables must be configured in your Fly.io application for the pipeline to function:

### AI & API Keys
- `GOOGLE_GEMINI_KEY`: API key for Google Gemini multimodal models.
- `OPENAI_API_KEY`: API key for Whisper speech-to-text processing.
- `LIVEBLOCKS_SECRET_KEY`: Used for collaborative features and comment syncing.
- `RESEND_API_KEY`: Required for sending notification emails.

### Database & Storage
- `SUPABASE_URL`: Your Supabase project URL.
- `SUPABASE_KEY`: The public/anon key (if required by client).
- `SUPABASE_SERVICE_ROLE_KEY`: **Critical** for backend operations and bypassing RLS in the pipeline.

### Monitoring & Orchestration
- `PREFECT_API_URL`: Connection string for your Prefect Cloud or self-hosted server.
- `PREFECT_API_KEY`: Authentication key for Prefect.
- `SENTRY_DSN`: (Optional) Error tracking for the Python pipeline.

---

## Deployment Commands

### Setting Secrets
Before your first deployment, set the required secrets:
```bash
fly secrets set GOOGLE_GEMINI_KEY=... SUPABASE_SERVICE_ROLE_KEY=... PREFECT_API_KEY=...
```

### Deploying Specific Groups
You can scale or deploy specific process groups to different regions to be closer to the radio station stream sources:

```bash
# Deploy the configuration
fly deploy

# Scale the Stage 1 workers for higher concurrency
fly scale count stage_1=3
fly scale count stage_3=2
```

### Regional Considerations
Because VERDAD monitors live radio broadcasts, it is recommended to deploy `initial_disinformation_detection` workers in Fly.io regions physically closest to the target radio station's streaming origin to minimize latency and connection interruptions.
