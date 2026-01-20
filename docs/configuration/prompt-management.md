# Prompt Management

VERDAD utilizes a versioned prompt management system to ensure consistency and traceability across its multi-stage AI pipeline. Prompts are treated as managed assets, allowing researchers and developers to iterate on detection heuristics and analysis criteria without modifying the core application code.

**See also:** [Prompt Management Advanced Guide](prompt-management-advanced.md) for detailed versioning, script usage, and iterative refinement workflows.

## Core Concepts

Prompt management in VERDAD is built around the following principles:

*   **Stage-Specific Context:** Each pipeline stage (Initial Detection, In-depth Analysis, Review) has its own dedicated prompt template.
*   **Versioning:** Prompts are stored in the `prompt_versions` table, allowing for side-by-side testing and historical auditing.
*   **Active Selection:** Only one prompt version is marked as `is_active` for a specific stage at any given time, providing a "single source of truth" for the production pipeline.

## Prompt Retrieval Interface

The pipeline interacts with prompts through the `SupabaseClient`. The system typically retrieves the currently active prompt for a specific stage.

### Retrieving the Active Prompt

To fetch the prompt currently used in production for a specific stage:

```python
from processing_pipeline.supabase_utils import SupabaseClient
from processing_pipeline.constants import PromptStage

client = SupabaseClient(url, key)

# Fetch the active prompt for Stage 3 (In-depth Analysis)
active_prompt = client.get_active_prompt(PromptStage.STAGE_3)

print(f"Using Version ID: {active_prompt['id']}")
print(f"System Instructions: {active_prompt['system_instructions']}")
```

### Retrieving a Specific Version

If a specific historical analysis needs to be re-run using the original prompt:

```python
# Fetch a specific prompt version by its UUID
specific_prompt = client.get_prompt_by_id("3b39f536-7466-44da-9772-b10dcf72c6be")
```

## Prompt Stages

Prompts are categorized by `PromptStage` to align with the pipeline architecture:

| Stage | Description | Key Focus |
| :--- | :--- | :--- |
| `STAGE_1` | Initial Detection | High-recall screening of raw audio/transcripts to identify potential disinformation. |
| `STAGE_3` | In-depth Analysis | Complex analysis involving claim extraction, political leaning, and emotional tone. |
| `STAGE_4` | Analysis Review | Validation and refinement of the analysis generated in Stage 3. |

## Data Schema for Prompts

Users managing prompts via the database should adhere to the following structure within the `prompt_versions` table:

*   **`id`** (UUID): Unique identifier for the version.
*   **`stage`** (String): The pipeline stage this prompt belongs to (e.g., `stage_1`, `stage_3`).
*   **`system_instructions`** (Text): The core instructions provided to the LLM defining its persona and task.
*   **`user_template`** (Text): The template for the user message, often containing placeholders for dynamic data like `{{transcription}}` or `{{metadata}}`.
*   **`is_active`** (Boolean): Boolean flag. Setting this to `true` for a stage will automatically deprecate older active prompts for that stage in the execution flow.
*   **`model_params`** (JSONB): Optional configuration for temperature, top-p, and max output tokens specific to this prompt version.

## Best Practices for Prompt Iteration

1.  **Safety Settings:** All prompts are executed with safety filters disabled (configured in `get_safety_settings()`) to ensure the model can analyze harmful disinformation without being blocked by provider-level content filters.
2.  **Structured Output:** For Stage 3 and Stage 4, prompts must explicitly instruct the model to return valid JSON that conforms to the Pydantic models defined in `src/processing_pipeline/stage_3_models.py`.
3.  **Bilingual Requirements:** Since VERDAD focuses on Spanish and Arabic broadcasts, system instructions should specify that titles, summaries, and explanations must be generated in both the original language and English.
