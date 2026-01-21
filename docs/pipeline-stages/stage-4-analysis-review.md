# Stage 4: Analysis Review

## Stage 4: Analysis Review

Stage 4 serves as the automated validation and quality assurance layer of the VERDAD pipeline. In this stage, a multimodal AI model reviews the in-depth analysis generated in Stage 3 to ensure consistency, factual grounding, and logical soundness before the findings are presented to human researchers.

### Overview

The primary goal of Analysis Review is to perform a "sanity check" on the suspected disinformation. The model evaluates whether the claims identified in Stage 3 are actually supported by the audio evidence, whether the evidence provided is logically defensible, and if the scoring is consistent with the severity of the claims.

### Execution

The review process is orchestrated as a Prefect flow. It can be triggered for specific snippets or run as a continuous worker process.

**Deployment Configuration:**
```python
# From src/processing_pipeline/main.py
case "analysis_review":
    deployment = analysis_review.to_deployment(
        name="Stage 4: Analysis Review",
        concurrency_limit=100,
        parameters=dict(snippet_ids=[], repeat=True),
    )
    serve(deployment, limit=100)
```

### Main Interface: `Stage4Executor`

The `Stage4Executor` is the primary interface for running the review logic. It requires the original transcription, the specific flagged snippet, and the JSON analysis produced by Stage 3.

#### Usage Example

```python
from processing_pipeline.stage_4 import Stage4Executor, prepare_snippet_for_review

# 1. Prepare data from previous analysis
transcription, disinformation_snippet, metadata, analysis_json = prepare_snippet_for_review(previous_analysis)

# 2. Run the review
response, grounding_metadata = Stage4Executor.run(
    transcription=transcription,
    disinformation_snippet=disinformation_snippet,
    metadata=metadata,
    analysis_json=analysis_json,
)
```

### Input and Output Data

#### Inputs
*   **Transcription**: The full text of the audio clip.
*   **Disinformation Snippet**: The specific text segment flagged for review.
*   **Metadata**: Information about the radio station, location, and recording time.
*   **Analysis JSON**: The full structured output from Stage 3 (claims, emotional tone, political leaning, etc.).

#### Outputs
The stage returns a refined analysis object and **Grounding Metadata**. The grounded metadata contains specific links back to the source text to ensure the AI isn't "hallucinating" claims that don't exist in the audio.

### Validation Criteria

The review stage applies a `ValidationChecklist` to verify the quality of the analysis:

*   **Specific Claims Quoted**: Ensures the analysis uses direct quotes rather than paraphrasing.
*   **Evidence Provided**: Checks if every claim is backed by specific evidence from the transcript.
*   **Scoring Falsity**: Validates the confidence score assigned to the disinformation.
*   **Defensibility**: Evaluates if the findings would be considered defensible by professional fact-checkers.
*   **Consistency**: Ensures the Spanish and English explanations align perfectly.

### Post-Processing and Vector Updates

Once a snippet passes Stage 4 review, the system performs several automated maintenance tasks to keep the database and front-end in sync:

1.  **Label Assignment**: Finalized disinformation categories are converted into database labels and assigned to the snippet.
2.  **Vector Re-indexing**: The system deletes the old vector embedding for the snippet. This triggers a Stage 5 (Embedding) event to re-index the snippet with its refined analysis, improving the accuracy of the platform's similarity search.

```python
# Internal utility handling the finalization logic
postprocess_snippet(
    supabase_client, 
    snippet_id, 
    disinformation_categories
)
```

### Configuration

Stage 4 utilizes Google's Gemini models with specific safety settings to ensure the model does not refuse to analyze sensitive or controversial content (which is often the nature of disinformation).

*   **Safety Thresholds**: All categories (Hate Speech, Harassment, etc.) are set to `BLOCK_NONE` to allow for the objective analysis of potentially harmful content without model interference.
*   **Model Routing**: While Stage 3 handles heavy analysis, Stage 4 focuses on verification and can be configured to use different Gemini variants (Flash vs. Pro) depending on the required depth of the review.
