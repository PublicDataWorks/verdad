# BigQuery Archival

## BigQuery Archival

VERDAD utilizes Google BigQuery as its primary analytical data warehouse for long-term storage and large-scale research. While the live application runs on Postgres (Supabase) to support the interactive review process, BigQuery is the repository for the final, structured output of the entire AI pipeline.

This archival process ensures that journalists and researchers can perform complex SQL queries across millions of records without impacting the performance of the real-time monitoring system.

### Overview

The archival process captures the high-fidelity results generated in **Stage 3 (In-Depth Analysis)** and **Stage 4 (Analysis Review)**. The data archived includes:

*   **Transcription & Translations:** Full text of the snippet in its original language and English.
*   **Structured Analysis:** Detailed disinformation categories, confidence scores, and emotional tone analysis.
*   **Political Leaning:** Calculated scores and evidence regarding political bias.
*   **User Feedback:** Comments and validation labels provided by researchers via the front-end.
*   **Metadata:** Station information, timestamps, and geographic data.

### Data Schema

The BigQuery tables are structured to match the `Stage3Output` Pydantic models. Key fields available for analysis include:

| Field | Type | Description |
| :--- | :--- | :--- |
| `snippet_id` | STRING | Unique identifier for the audio snippet. |
| `recorded_at` | TIMESTAMP | The time the original broadcast was recorded. |
| `station_code` | STRING | The identifier for the radio station (e.g., `WAXY - 790 AM`). |
| `primary_language` | STRING | The detected language (Spanish, Arabic, etc.). |
| `overall_confidence` | INTEGER | Pipeline confidence score (0-100). |
| `political_score` | FLOAT | Political leaning score (-1.0 to 1.0). |
| `analysis_json` | JSON | The complete structured output from the Gemini LLM. |

### Querying Archival Data

Researchers can access the `verdad_archival` dataset to perform cross-station or longitudinal studies.

**Example: Finding high-intensity emotional content across Florida stations**

```sql
SELECT 
  title.english,
  summary.english,
  metadata.radio_station_name,
  tone.intensity,
  tone.explanation.english as tone_reason
FROM `your-project.verdad_archival.snippets`,
UNNEST(emotional_tone) as tone
WHERE metadata.location_state = 'Florida'
  AND tone.intensity > 80
ORDER BY recorded_at DESC
LIMIT 100;
```

### Integration with the Pipeline

The archival process is triggered as an automated stage within the Prefect orchestration. Once a snippet has been reviewed or has passed through the full analysis suite, the `bigquery_archival` task (internal) formats the `Stage3Output` and `Stage4` modifications into a BigQuery-compatible row.

#### Usage in Code

While primarily an automated backend process, the archival logic relies on the environment configuration for project and dataset identification:

```python
# Internal configuration used by the Prefect pipeline
BIGQUERY_PROJECT_ID = "your-google-cloud-project"
BIGQUERY_DATASET_ID = "verdad_archival"
BIGQUERY_TABLE_ID = "snippets"
```

### Data Freshness

The archival sync typically runs in batches. Data is moved from the live Postgres instance to BigQuery:
1.  **Automatically:** After a snippet reaches a "Completed" status in the `Stage 4: Analysis Review` flow.
2.  **Periodically:** Via a scheduled sync for community comments and researcher labels to ensure the archival record reflects the most recent human-in-the-loop feedback.
