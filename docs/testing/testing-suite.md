# Testing Suite

## Testing Suite

VERDAD employs a robust testing strategy to ensure the reliability of its multi-stage AI pipeline. The suite focuses on validating orchestration logic, data flow between stages, and the integrity of the AI analysis.

### Prerequisites

Before running the tests, ensure you have the development dependencies installed and your environment variables configured.

```bash
pip install pytest
```

### Running the Test Suite

The primary testing tool is **Pytest**. You can run the full pipeline test suite from the root directory:

```bash
pytest tests/processing_pipeline/test_main_processing.py
```

### Local Testing Environment

To facilitate unit testing without the overhead of the Prefect orchestration engine, the system uses a decorator toggle. This allows you to run pipeline functions as standard Python functions.

Set the following environment variable to disable Prefect wrappers during local testing:

```bash
# Disable Prefect orchestration for standard unit tests
export ENABLE_PREFECT_DECORATOR=false
```

### Pipeline Stage Testing

The testing suite validates that the `FLY_PROCESS_GROUP` environment variable correctly triggers the intended pipeline stages. This ensures that when the system scales on Fly.io, each worker initializes the correct stage (e.g., `initial_disinformation_detection`, `audio_clipping`, `in_depth_analysis`).

#### Mocking and Fixtures
The suite uses several fixtures to isolate the pipeline logic from external services:

### Manual Stage 4 Validation

A dedicated test entry point exists in `src/main.py` for manual verification of the **Stage 4: Analysis Review** process. This script performs a real-world integration test by fetching a snippet from Supabase and running it through the Gemini LLM.

**Usage:**

```bash
python src/main.py
```

**What this tests:**
1.  **Supabase Connectivity**: Fetches a specific snippet by ID.
2.  **Data Preparation**: Validates `prepare_snippet_for_review` logic (transcription, snippet extraction, and metadata formatting).
3.  **LLM Integration**: Sends the payload to `Stage4Executor` and prints the structured JSON response and grounding metadata.

### Test Coverage Areas

| Area | Description |
| :--- | :--- |
| **Deployment Logic** | Validates that `match process_group` logic assigns correct parameters (concurrency limits, retry logic) to each stage. |
| **Environment Handling** | Ensures the system correctly loads configurations and handles missing environment variables gracefully. |
| **Data Models** | Validates that Pydantic models in `stage_3_models.py` correctly parse and validate complex LLM outputs (e.g., `PoliticalLeaning`, `ConfidenceScores`). |
| **Service Integration** | Tests the interaction between the Express server, Liveblocks webhooks, and the Supabase database. |

### Integration Testing with Supabase

For tests requiring database interaction, the system uses a `SupabaseClient` utility. When writing new tests that involve database writes, ensure you are targeting a development schema or using the provided RPC (Remote Procedure Call) mocks to prevent polluting production data.
