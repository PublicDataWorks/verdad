# Docker & Containerization

## Docker & Containerization

VERDAD utilizes a containerized architecture to manage its multi-stage AI pipeline and auxiliary services. The system is designed to run primarily on **Fly.io** using a polymorphic Docker approach where a single image can take on different roles (workers) based on environment configuration.

### Processing Pipeline Workers

The core of the VERDAD pipeline is a Python-based worker system orchestrated by **Prefect**. The specific stage or task a container performs is determined by the `FLY_PROCESS_GROUP` environment variable.

#### Configuration via `FLY_PROCESS_GROUP`

When deploying the pipeline image, set the `FLY_PROCESS_GROUP` variable to one of the following values to initialize the corresponding service:

| Process Group | Purpose |
| :--- | :--- |
| `initial_disinformation_detection` | Runs Stage 1: Detects potential disinformation in raw audio. |
| `audio_clipping` | Runs Stage 2: Extracts specific audio segments for analysis. |
| `in_depth_analysis` | Runs Stage 3: Performs detailed AI analysis on audio snippets. |
| `analysis_review` | Runs Stage 4: Refines and reviews previous analysis steps. |
| `embedding` | Runs Stage 5: Generates vector embeddings for semantic search. |
| `regenerate_timestamped_transcript` | Maintenance: Re-runs transcription for existing records. |

#### Running a Worker Locally

To run a specific pipeline stage locally using Docker, use the following pattern:

```bash
docker run -e FLY_PROCESS_GROUP=initial_disinformation_detection \
           -e GOOGLE_GEMINI_KEY=your_key \
           -e SUPABASE_URL=your_url \
           -e SUPABASE_KEY=your_key \
           verdad-pipeline-image
```

### Backend Server

The backend (located in the `/server` directory) is a Node.js/TypeScript Express application. It handles authentication for Liveblocks, manages webhooks, and synchronizes comment data with Supabase.

#### API Endpoints
The containerized server exposes several critical paths:
- `POST /api/liveblocks-auth`: Handles user authentication for collaborative features.
- `POST /api/webhooks/liveblocks`: Listens for real-time interaction events.
- `GET /`: Health check endpoint.

### Environment Configuration

The containers require a specific set of environment variables to function correctly across the pipeline and server.

#### Pipeline Variables (Python)
- `GOOGLE_GEMINI_KEY`: API key for Google Gemini multimodal LLM.
- `SUPABASE_URL` / `SUPABASE_KEY`: Connection details for the Postgres database.
- `SENTRY_DSN`: (Optional) For error tracking and monitoring.
- `ENABLE_PREFECT_DECORATOR`: Set to `true` (default) to enable Prefect flow orchestration.

#### Server Variables (Node.js)
- `LIVEBLOCKS_SECRET_KEY`: Integration key for real-time collaboration.
- `SUPABASE_SERVICE_ROLE_KEY`: Required for administrative database access (e.g., syncing comments).
- `RESEND_API_KEY`: API key for sending notification emails.
- `SLACK_NOTIFICATION_EMAIL`: Destination for forwarding system notifications to Slack.

### Orchestration and Deployment

VERDAD is architected to leverage **Prefect** for workflow management. Within the containers, the system uses `prefect.serve()` to create long-running deployments that listen for scheduled tasks or manual triggers from the Prefect Cloud or a local server instance.

```python
# Internal logic used by the container to serve workers
deployment = initial_disinformation_detection.to_deployment(
    name="Stage 1: Initial Disinformation Detection",
    concurrency_limit=100
)
serve(deployment)
```

For production deployments, each `FLY_PROCESS_GROUP` should be scaled independently based on the volume of incoming audio data. Stage 1 (Detection) and Stage 2 (Clipping) typically require higher concurrency limits than Stage 5 (Embedding).
