# Maintenance Scripts

## Maintenance and Administrative Scripts

The VERDAD platform includes several scripts and automated flows to manage data synchronization, handle pipeline corrections, and perform diagnostic tests.

### Data Synchronization

#### Liveblocks to Postgres Comment Sync
The system includes a script to synchronize collaborative data (comments and threads) from Liveblocks into the Postgres/Supabase database. This ensures that analyst discussions are backed up and available for internal reporting.

**Execution:**
Navigate to the `server` directory and run the sync utility:
```bash
# Using the compiled entry point
npm run start
```

**Key Operations:**
- **Room Discovery:** Fetches all active rooms from Liveblocks.
- **Thread & Comment Retrieval:** Iterates through rooms to extract all threads and their associated comments.
- **Batch Upsert:** Uses `p-limit` to handle concurrent requests and upserts data into the `comments` table in chunks of 100 to ensure database stability.

---

### Pipeline Maintenance & Undo Operations

The processing pipeline provides specific administrative flows to correct errors or re-run analysis if models or prompts are updated. These are managed via the `FLY_PROCESS_GROUP` environment variable within the Prefect orchestration layer.

#### Re-running Analysis
| Process Group | Description |
| :--- | :--- |
| `regenerate_timestamped_transcript` | Re-runs Whisper ASR for specific Stage 1 responses to fix transcription issues. |
| `redo_main_detection` | Re-triggers the Stage 1 Gemini screening for specific responses. |

#### Undo Operations (Cleanup)
These scripts are used to remove data from the database and storage when a processing run needs to be completely invalidated.

| Process Group | Description | Input Parameters |
| :--- | :--- | :--- |
| `undo_disinformation_detection` | Removes Stage 1 detection records. | `audio_file_ids` (List) |
| `undo_audio_clipping` | Deletes generated audio snippets and metadata from Stage 2. | `stage_1_llm_response_ids` (List) |

**Usage Example (Fly.io/Prefect):**
To run an undo operation, deploy the container with the corresponding environment variable:
```bash
env FLY_PROCESS_GROUP="undo_audio_clipping" python src/processing_pipeline/main.py
```

---

### Diagnostic & Testing Scripts

#### Stage 4 Review Simulator
The `src/main.py` script serves as a standalone test runner for the Stage 4 (Analysis Review) executor. It allows developers to verify how the Gemini model handles specific snippets without running the full pipeline.

**Usage:**
```bash
python src/main.py
```

**Functionality:**
1. Fetches a specific snippet from Supabase by ID.
2. Prepares the context (transcription, metadata, and previous Stage 3 analysis).
3. Executes the `Stage4Executor` to generate a refined analysis.
4. Outputs the raw JSON result and grounding metadata to the console for verification.

---

### Database Utility Interface

The `SupabaseClient` class in `src/processing_pipeline/supabase_utils.py` acts as the administrative interface for database state changes. While used internally by the pipeline, it can be utilized in maintenance scripts for manual state resets.

**Common Maintenance Tasks:**
- `set_audio_file_status(id, status)`: Manually reset a file to `pending` or `failed`.
- `set_snippet_status(id, status)`: Manually update snippet progress.
- `delete_vector_embedding_of_snippet(snippet_id)`: Force a snippet to be re-indexed in the vector database by deleting its current embedding.

**Example: Manually Resetting a Snippet for Re-Analysis**
```python
from processing_pipeline.supabase_utils import SupabaseClient

db = SupabaseClient(url, key)
# Reset status to allow Stage 3 to pick it up again
db.set_snippet_status("snippet-uuid-here", "pending")
```

---

### Notification Health Checks

The system utilizes Resend and Slack for administrative alerts.
- **Email Templates:** Managed via the `email_template` table. Templates can be refreshed or tested using `server/src/services/templateService.ts`.
- **Slack Notifications:** Triggered via `sendSlackNotification`. This can be called within administrative scripts to notify the team of completed maintenance tasks or batch processing failures.
