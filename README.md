# VERDAD

VERDAD is an open-source platform designed to detect and analyze potential disinformation in radio broadcasts (across any language, but with a primary focus on Spanish and Arabic). Our five-stage AI pipeline is powered by Google's multimodal Gemini 2.5 models (`gemini-2.5-flash`, `gemini-2.5-pro`) with OpenAI `text-embedding-3-large` embeddings for knowledge-base retrieval and semantic search. The audio recording pipeline is orchestrated by Prefect running on Fly.io. This system includes continuous audio recording, preliminary detection by a multimodal model, detailed transcription with timestamps, audio clip generation, nuanced content analysis, an agentic fact-checking review, and vector embedding to generate structured output that is finally stored in a Postgres database and displayed in an interactive [front-end](https://github.com/publicdataworks/verdad-frontend) where support journalists and researchers can review suspected snippets of mis/disinformation upvote the existing labels or add their own custom labels and discuss with each other in comments. Their feedback will also be used to improve the heuristics for flagging suspected mis/disinfo more accurately going forward.

The project's big goals are:

1. to provide visibility and data that can be used by trustworthy journalists to help disseminate timely factchecking and accurate counter narratives in response to specific mis/disinformation patterns;
2. to support investigations (big and small) into trends of mis/disinformation campaigns across regions and over time.

## Project Overview

The VERDAD project addresses the critical challenge of monitoring and analyzing potential disinformation on radio stations who are targetted at immigrant communities. This medium represents a significant vector for the spread of mis/disinformation but it has received less systematic scrutiny than social media platforms.

### Key Features

-   Continuous recording and monitoring of Spanish-language radio stations
-   Multi-stage AI analysis pipeline for disinformation detection
-   Language-aware content analysis with cultural context understanding
-   Collaborative platform for analysts to review and validate findings
-   Structured data output for further research and analysis

## Technical Architecture

VERDAD employs a five-stage pipeline (`src/processing_pipeline/stage_1` ... `stage_5`), each stage a Prefect flow that polls Supabase for work:

### Stage 1: Initial Disinformation Detection

**Input:**

-   Full audio file (5-15 minutes)
-   Metadata (station info, timestamps, etc.)

**Process:**

-   Uses Gemini 2.5 Flash (`gemini-2.5-flash`) for an initial transcription and a high-recall screening pass, augmented with knowledge-base context retrieved via OpenAI embeddings
-   Only if something is flagged: generates a timestamped transcription with Gemini 2.5 Flash over 20-second audio segments, then runs the main detection prompt

**Output:**

-   Flagged snippet timestamps
-   Basic categorization
-   Initial confidence scores

### Stage 2: Audio Clipping

**Input:**

-   Original audio files
-   Timestamps from Stage 1

**Process:**

-   Extracts audio segments corresponding to flagged content
-   Includes configurable context windows (before/after)
-   Processes metadata for segment identification

**Output:**

-   Individual audio clips for each flagged segment
-   Structured metadata for each clip
-   Storage paths and reference data

### Stage 3: In-Depth Analysis

**Input:**

-   Extracted audio clips
-   Stage 1 metadata and categorization
-   Cultural context data

**Process:**

-   Uses Gemini 2.5 Pro (`gemini-2.5-pro`, falling back to `gemini-2.5-flash` on server errors) with SearXNG web-search tools for fact checking
-   Performs multi-dimensional content evaluation
-   Snippets with overall confidence >= 95 are routed to Stage 4 review; the rest are marked `Processed`

**Output:**
Structured JSON including:

-   Detailed transcription and translation
-   Disinformation category analysis
-   Confidence scores
-   Emotional tone analysis
-   Political leaning assessment
-   Cultural context notes

### Stage 4: Analysis Review

**Input:** high-confidence Stage 3 snippets (`Ready for review`)

**Process:**

-   A Google ADK agent pipeline on Gemini 2.5 Pro: knowledge-base researcher and web researcher (SearXNG via MCP) run in parallel, a reviewer revises the analysis, a knowledge-base updater records new findings
-   The original Stage 3 analysis is kept in `snippets.previous_analysis`

**Output:** revised analysis, grounding metadata and `reviewed_by` on the snippet; labels assigned from the final categories

### Stage 5: Embedding

-   Builds a text document from each processed snippet and embeds it with OpenAI `text-embedding-3-large` (L2-normalized) into `snippet_embeddings` for semantic search

## Data Schema

### Audio Files Table

```sql
audio_files {
  id: uuid
  radio_station_name: string
  radio_station_code: string
  location_state: string
  recorded_at: timestamp
  recording_day_of_week: string
  file_path: string
  file_size: integer
  status: enum['New', 'Processing', 'Processed', 'Error']
  error_message: string?
}
```

### Stage 1 LLM Responses Table

```sql
stage_1_llm_responses {
  id: uuid
  audio_file: foreign_key(audio_files)
  initial_transcription: jsonb
  initial_detection_result: jsonb
  timestamped_transcription: jsonb
  detection_result: jsonb
  status: enum['New', 'Processing', 'Processed', 'Error']
  error_message: string?
}
```

### Snippets Table

```sql
snippets {
  id: uuid
  audio_file: foreign_key(audio_files)
  stage_1_llm_response: foreign_key(stage_1_llm_responses)
  file_path: string
  file_size: integer
  recorded_at: timestamp
  duration: interval
  start_time: interval
  end_time: interval
  transcription: jsonb
  translation: jsonb
  title: jsonb
  summary: jsonb
  explanation: jsonb
  disinformation_categories: jsonb[]
  keywords_detected: string[]
  language: jsonb
  confidence_scores: jsonb
  emotional_tone: jsonb[]
  context: jsonb
  political_leaning: jsonb
  status: enum['New', 'Processing', 'Processed', 'Error']
  error_message: string?
}
```

## Key Components

### Recording System

-   Supports multiple radio station formats
-   Configurable recording durations and quality settings
-   Robust error handling and recovery
-   Cloud storage integration (Cloudflare R2)

### Analysis Pipeline

-   Language-agnostic design with Spanish/Arabic priority
-   Cultural context awareness
-   Continuous learning from analyst feedback
-   Structured output for research use

### Database Architecture

-   PostgreSQL with pgvector extension
-   Efficient storage of audio segments
-   Comprehensive metadata tracking
-   Version control for analysis models

## Getting Started

### Prerequisites

-   Python 3.11+
-   Node.js 20+ (for Gemini CLI)
-   A Supabase project (Postgres + pgvector); see `supabase/`
-   FFmpeg
-   PulseAudio
-   Chrome/Chromium (for web radio capture)

### Installation

1. Clone the repository:

```bash
git clone git@github.com:PublicDataWorks/verdad.git
cd verdad
```

2. Create a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate  # On Windows, use `.venv\Scripts\activate`
```

3. Install Python dependencies:

```bash
pip install -r requirements.txt
```

4. Install Gemini CLI:

```bash
npm install -g @google/gemini-cli
```

Verify installation:

```bash
gemini --version
```

5. Set up environment variables:

```bash
cp .env.sample .env
# Edit .env with your configuration
```

### Development Setup

1. Run the checks (this is exactly what CI runs on every pull request):

```bash
make check      # ruff check + pytest
make lint       # ruff only
make test       # pytest with the coverage gate
```

The coverage gate is `fail_under` in `pyproject.toml`; it is set to the current real coverage and only moves up.
`ffmpeg` must be on your PATH (stage 2 tests decode real mp3s). `ruff` rule `I` (import sorting) is intentionally off until a formatting-only commit lands.

2. Optional local hooks:

```bash
pip install pre-commit && pre-commit install   # ruff on staged files
./hooks/install-hooks.sh                      # pre-push: ruff + pytest without the coverage gate
```

3. HTML coverage report: `./scripts/coverage.sh` (writes `htmlcov/`).

### Configuration

All environment variables, with a one-line explanation each, are listed in [`.env.sample`](.env.sample). The main ones:

-   `GOOGLE_GEMINI_KEY`: Gemini API key (stages 1, 3, 4)
-   `OPENAI_API_KEY`: OpenAI key for `text-embedding-3-large` (stage 5, knowledge-base retrieval)
-   `R2_*`: Cloudflare R2 storage configuration
-   `SUPABASE_URL`, `SUPABASE_KEY`: Supabase database configuration
-   `SEARXNG_URL`: SearXNG instance for web search (stages 3 and 4)

### Running the Pipeline

In production every worker is a Fly machine whose `FLY_PROCESS_GROUP` selects one Prefect deployment; without that variable `src/processing_pipeline/main.py` and `src/recording.py` raise `ValueError`. See [`docs/OPERATIONS.md`](docs/OPERATIONS.md) for the apps, process groups and how to trigger a run.

To run a single stage locally as plain Python (no Prefect server; uses whatever `.env` points at):

```bash
python scripts/run_stage.py --stage 1 --audio-file-id <uuid>
python scripts/run_stage.py --stage 3 --snippet-id <uuid> --skip-review
python scripts/run_stage.py --stage 4 --snippet-id <uuid>
```

Prompts are read from the `prompt_versions` table, not from `prompts/`. To change one, edit the file, bump its
entry in `prompts/manifest.json` and open a PR: CI evaluates the change and, on merge to `main`, imports it
(`docs/PROMPT_EVALUATION.md`). To import by hand:

```bash
PYTHONPATH=.:src python src/scripts/import_prompts_to_db.py import --from-manifest --dry-run
```

## Contributing

We welcome contributions! Read [`AGENTS.md`](AGENTS.md) for the repo layout, commands, gotchas and rules (it applies to humans and coding agents alike), run `make check` before pushing, and open a pull request against `main`.

## Deployment

VERDAD runs on Fly.io as separate apps for the Prefect server (plus a cron machine), audio recording, the processing stages, a SearXNG instance and the Express server; the database is Supabase. Each app has a `fly.*.toml` in the repository and is deployed manually with `fly deploy -c <file>`. See [`docs/OPERATIONS.md`](docs/OPERATIONS.md).

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

VERDAD is a project of Public Data Works, developed in collaboration with the Invisible Institute and supported by various organizations working to combat disinformation in Spanish-language media.

## Contact

For questions or support, please open an issue on GitHub or contact the maintainers at [contact information].
