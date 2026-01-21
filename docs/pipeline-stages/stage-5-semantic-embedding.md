# Stage 5: Semantic Embedding

## Overview

Stage 5 of the VERDAD pipeline focuses on **Semantic Embedding**. Once a snippet has undergone in-depth analysis (Stage 3) and review (Stage 4), the system generates high-dimensional vector representations of the content. These embeddings enable advanced platform features such as:

*   **Similarity Search:** Identifying snippets with similar rhetorical patterns or claims.
*   **Trend Clustering:** Grouping related disinformation campaigns across different radio stations and timeframes.
*   **Deduplication:** Detecting repetitive broadcasts of the same misleading content.

## Process Flow

The embedding stage is an automated process that typically runs asynchronously after the analysis phases are complete.

1.  **Identification:** The system identifies snippets that are either missing a vector embedding or have had their existing embedding invalidated (e.g., after a significant analysis update).
2.  **Vector Generation:** The text-based analysis (including the title, summary, and primary transcription) is passed to an embedding model.
3.  **Storage:** The resulting vector is stored in the Postgres database (via `pgvector`) and indexed for fast similarity retrieval.

## Execution and Deployment

Stage 5 is orchestrated by Prefect and is designed to run as a continuous worker process.

### Running the Embedding Worker
To start a worker dedicated to Stage 5, set the `FLY_PROCESS_GROUP` environment variable to `embedding`. This initializes a Prefect deployment that monitors the database for pending snippets.

```bash
export FLY_PROCESS_GROUP="embedding"
python -m processing_pipeline.main
```

### Configuration Parameters
The `embedding` deployment supports the following parameters:

| Parameter | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `repeat` | `bool` | `True` | Whether the task should continuously loop and check for new snippets. |
| `concurrency_limit` | `int` | `100` | The maximum number of simultaneous embedding operations. |

## Database Integration

The embeddings are managed through the `SupabaseClient` within the `processing_pipeline`. 

### Triggering Re-embedding
If a snippet's content is updated and requires a fresh vector representation, the system uses a utility function to delete the existing embedding. This deletion acts as a "dirty flag," signaling the Stage 5 worker to re-process the snippet.

```python
from processing_pipeline.processing_utils import delete_vector_embedding_of_snippet

# Internal utility to trigger a new embedding for a specific snippet
delete_vector_embedding_of_snippet(supabase_client, snippet_id="your-snippet-uuid")
```

### Data Storage
Embeddings are stored in the `snippets` table (or a related vector table) within the Postgres database. This allows researchers to perform similarity queries using standard SQL:

```sql
-- Example of finding similar snippets via the database
SELECT id, title 
FROM snippets 
ORDER BY embedding <=> '[vector_data]' 
LIMIT 5;
```

## Internal Utilities

While primarily automated, Stage 5 utilizes internal logic within `src/processing_pipeline/stage_5.py` to interface with the embedding models. 

*   **Input Data:** Primarily uses the `Stage3Output` and `Stage4` revised analysis.
*   **Model:** Utilizes standard embedding models (configured via environment variables) to ensure cross-language semantic consistency between Spanish, Arabic, and English translations.
