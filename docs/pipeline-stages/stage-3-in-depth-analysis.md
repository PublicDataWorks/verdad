# Stage 3: In-Depth Analysis

## Overview

Stage 3 of the VERDAD pipeline performs a comprehensive, multi-dimensional analysis of audio snippets previously flagged in Stage 1 and clipped in Stage 2. While Stage 1 focuses on high-recall detection, Stage 3 utilizes advanced LLM capabilities to provide a deep dive into the content, language, emotional subtext, and political orientation of the broadcast.

This stage produces structured data used by journalists and researchers to validate disinformation patterns and understand the rhetorical strategies employed by broadcasters.

## Structured Analysis Model

The output of Stage 3 is governed by a strict Pydantic schema (`Stage3Output`), ensuring that every analyzed snippet contains consistent, actionable metadata.

### 1. Content and Context
Stage 3 generates a full transcription and translation, providing the necessary surrounding context for the flagged claim.

| Field | Description |
| :--- | :--- |
| `transcription` | Complete transcript of the audio clip in the original language. |
| `translation` | English translation of the transcription. |
| `title` / `summary` | Bilingual (Spanish/English) descriptive titles and objective summaries. |
| `context` | Specifically identifies the "main" snippet versus the "before" and "after" segments. |

### 2. Disinformation Analysis & Claims
The system extracts specific claims and evaluates them against evidence.

- **Claims**: A list of objects containing the direct quote, evidence of why it is misleading, and a confidence score.
- **Validation Checklist**: An internal quality control mechanism where the model confirms if claims are quoted, evidence is provided, and the analysis is defensible to fact-checkers.
- **Confidence Scores**: Provides a granular breakdown of confidence for the overall analysis and specific disinformation categories.

### 3. Emotional Tone Detection
VERDAD analyzes the "how" of the message, looking for emotional manipulation or high-intensity rhetoric.

```python
# Example of Emotional Tone Data Structure
{
  "emotion": {"spanish": "Miedo", "english": "Fear"},
  "intensity": 85,
  "evidence": {
    "vocal_cues": ["trembling voice", "rapid speech"],
    "phrases": ["¡Esto es una emergencia nacional!"],
    "patterns": ["Urgency", "Existential threat"]
  },
  "explanation": {
    "impact": "Increases audience anxiety and reduces critical thinking."
  }
}
```

### 4. Political Leaning Assessment
The pipeline evaluates the political orientation of the content on a scale from `-1.0` (Left) to `1.0` (Right).

- **Score**: A float value representing the leaning.
- **Evidence**: Analyzes policy positions, specific arguments made, rhetoric used, and sources cited.
- **Score Adjustments**: Records the reasoning for the final score and any adjustments made during the model's "thinking" process.

---

## Usage and Execution

Stage 3 is orchestrated as a Prefect flow. It can be run as a continuous worker or triggered for specific snippets.

### Running the Deployment
To start a worker dedicated to Stage 3 analysis via the CLI:

```bash
# Set the process group to match the deployment configuration
export FLY_PROCESS_GROUP="in_depth_analysis"
python src/processing_pipeline/main.py
```

### Configuration Parameters
When deploying or triggering the flow, the following parameters are available:

| Parameter | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `snippet_ids` | `list` | `[]` | List of specific snippet UUIDs to analyze. |
| `repeat` | `bool` | `True` | If true, the worker will continuously poll for new snippets. |
| `skip_review` | `bool` | `True` | Whether to move directly to the next stage after analysis. |

---

## Post-Analysis Workflow

Once the analysis is complete, the pipeline automatically performs several maintenance tasks to prepare the data for the front-end:

1.  **Label Assignment**: The system parses the identified `disinformation_categories` and automatically creates and assigns labels (e.g., "Conspiracy Theory," "Hate Speech") to the snippet in the database.
2.  **Vector Invalidation**: It deletes any existing vector embeddings for the snippet. This triggers Stage 5 (Embedding) to generate a new vector based on the updated, rich metadata, ensuring the "Similar Snippets" feature remains accurate.
3.  **Database Update**: The status is updated to `ready_for_review` (if Stage 4 is active) or `completed`.

## Error Handling
If an analysis fails (e.g., due to API safety filters or malformed audio), the snippet status is updated to `error` and the specific reason is logged in the `error_message` field in the Postgres `snippets` table. Safety settings are configured by default to `BLOCK_NONE` for categories like `HATE_SPEECH` and `HARASSMENT` to ensure the model can actually analyze the disinformation it is intended to track.
