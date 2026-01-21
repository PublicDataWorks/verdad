# Prompt Management and Versioning

VERDAD supports versioning and dynamic management of prompts, enabling iterative refinement through user feedback.

## Prompt Import Script

The `src/scripts/import_prompts_to_db.py` script manages prompt versions in the database.

### Usage

```bash
# Import prompts with version numbering
python src/scripts/import_prompts_to_db.py import --version 1.0.0 --description "Initial import"

# Import without making version active (for review)
python src/scripts/import_prompts_to_db.py import --version 1.1.0 --description "Updated Stage 3" --no-active

# Preview changes without committing
python src/scripts/import_prompts_to_db.py import --version 1.0.0 --dry-run

# List existing prompt versions
python src/scripts/import_prompts_to_db.py list
```

### Version Format

Versions must follow semantic versioning: `MAJOR.MINOR.PATCH` (e.g., `1.0.0`)

### Supported Prompt Stages

The script manages prompts for:

| Stage | Components |
| :--- | :--- |
| **Stage 1** | System instruction, Detection prompt, Output schema |
| **Stage 3** | System instruction, Analysis prompt, Output schema |
| **Stage 4** | System instruction, Review prompt, Output schema |
| **Gemini Timestamped Transcription** | Generation prompt (alternative transcription method) |

### Database Schema

Each prompt version is stored with:
- **Version ID:** Unique identifier and version number
- **Stage:** Which pipeline stage (stage_1, stage_3, stage_4, etc.)
- **Components:** System instruction, user prompt, output schema
- **Associated Model:** Which LLM model it's designed for
- **Description:** Explanation of changes in this version
- **Active Status:** Whether this version is currently in use
- **Created At:** Timestamp of creation
- **Updated By:** User who imported the version

### Workflow

1. **Edit Prompts Locally:** Modify prompt files in the `prompts/` directory
2. **Validate Changes:** Test prompts locally with `ENABLE_PREFECT_DECORATOR=false`
3. **Dry Run:** Preview database changes with `--dry-run` flag
4. **Import as Inactive:** Import with `--no-active` for team review
5. **Activate Version:** After approval, set as active (manually via database or script)
6. **Monitor Performance:** Track metrics for new version
7. **Rollback if Needed:** Revert to previous version if issues arise

## Iterative Refinement Integration

User feedback collected through the front-end UI informs prompt updates:

1. **Feedback Collection:** Users upvote/downvote labels and add comments
2. **Analysis:** LLM reviews feedback and proposes heuristic adjustments
3. **Prompt Update:** System instructions and heuristics are refined
4. **Testing:** New prompts tested in staging environment
5. **Deployment:** Approved version activated and deployed to production

## Safety Settings

All LLM calls use custom safety settings configured in `src/processing_pipeline/processing_utils.py`:

```python
SafetySetting(
    category=HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
    threshold=HarmBlockThreshold.BLOCK_NONE,
)
SafetySetting(
    category=HarmCategory.HARM_CATEGORY_HATE_SPEECH,
    threshold=HarmBlockThreshold.BLOCK_NONE,
)
SafetySetting(
    category=HarmCategory.HARM_CATEGORY_HARASSMENT,
    threshold=HarmBlockThreshold.BLOCK_NONE,
)
SafetySetting(
    category=HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
    threshold=HarmBlockThreshold.BLOCK_NONE,
)
SafetySetting(
    category=HarmCategory.HARM_CATEGORY_CIVIC_INTEGRITY,
    threshold=HarmBlockThreshold.BLOCK_NONE,
)
```

**Note:** `CIVIC_INTEGRITY` is critical for analyzing election, voting, and political integrity content without the model refusing analysis due to safety filters.

## LLM Models

VERDAD supports multiple Gemini models:

| Model | Use Case |
| :--- | :--- |
| `gemini-1.5-flash` | Fast initial detection (Stage 1) |
| `gemini-1.5-pro-002` | Detailed analysis (Stage 3) |
| `gemini-2.5-flash` | Fast processing (newer alternative to 1.5 Flash) |
| `gemini-2.5-pro` | Advanced analysis (newer alternative to 1.5 Pro) |
| `gemini-flash-latest` | Latest Flash model |
| `gemini-flash-lite-latest` | Latest Lite model |

Model selection is configured in prompts via the `associated_model` field.

## Transcript Generation

Two transcription methods are available:

1. **OpenAI Whisper:** Standard ASR for general use
2. **Gemini Timestamped Transcription:** Alternative method using Gemini with custom prompt for more accurate timestamp alignment
