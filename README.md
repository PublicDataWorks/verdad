# VERDAD

VERDAD is an open-source platform designed to detect and analyze potential disinformation in radio broadcasts (across any language, but with a primary focus on Spanish and Arabic). Our multi-stage AI pipeline powered primarily by Google's multimodal Gemini LLM APIs and OpenAI Whisper speech-to-text (ASR) API. The audio recording pipeline is orchestrated by Prefect running on Fly.io. This system includes continuous audio recording, preliminary detection by a multimodal model, detailed transcription with timestamps, audio clip generation, and nuanced content analysis to generate structured output that is finally stored in a Postgres database and displayed in an interactive [front-end](https://github.com/publicdataworks/verdad-frontend) where support journalists and researchers can review suspected snippets of mis/disinformation upvote the existing labels or add their own custom labels and discuss with each other in comments. Their feedback will also be used to improve the heuristics for flagging suspected mis/disinfo more accurately going forward.

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

VERDAD employs a multi-stage pipeline architecture designed for scalability and accuracy:

### Stage 1: Initial Disinformation Detection

**Input:**

-   Full audio file (5-15 minutes)
-   Metadata (station info, timestamps, etc.)

**Process:**

-   Uses Gemini 1.5 Flash LLM for rapid initial screening
-   Applies simplified heuristics for high-recall detection
-   Generates timestamped transcriptions using OpenAI Whisper

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

-   Utilizes Gemini 1.5 Pro LLM for detailed analysis
-   Performs multi-dimensional content evaluation
-   Generates comprehensive annotations

**Output:**
Structured JSON including:

-   Detailed transcription and translation
-   Disinformation category analysis
-   Confidence scores
-   Emotional tone analysis
-   Political leaning assessment
-   Cultural context notes

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
-   PostgreSQL 13+
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
python3 -m venv venv
source venv/bin/activate  # On Windows, use `venv\Scripts\activate`
```

3. Install dependencies:

```bash
pip install -r requirements.txt
```

4. Set up environment variables:

```bash
cp .env.sample .env
# Edit .env with your configuration
```

### Development Setup

1. Install Git hooks to ensure code quality:

```bash
./hooks/install-hooks.sh
```

This installs a pre-push hook that:

-   Runs all tests
-   Verifies code coverage meets minimum requirements (80%)
-   Prevents pushing if tests fail or coverage is insufficient

To bypass the hook in exceptional cases (not recommended):

```bash
git push --no-verify
```

2. Run tests manually:

```bash
# Run tests with coverage report
./scripts/coverage.sh
```

### Configuration

Key environment variables:

-   `GOOGLE_GEMINI_KEY`: API key for Google's Gemini LLM
-   `OPENAI_API_KEY`: API key for OpenAI's Whisper API
-   `R2_*`: Cloudflare R2 storage configuration
-   `SUPABASE_*`: Supabase database configuration

### Running the Pipeline

1. Start the recording service:

```bash
python src/recording.py
```

2. Launch the processing pipeline:

```bash
python src/processing_pipeline/main.py
```

## Contributing

We welcome contributions! Please see our [Contributing Guidelines](CONTRIBUTING.md) for details on submitting pull requests, reporting issues, and contributing to documentation.

## Deployment

VERDAD is designed to run on Fly.io, with separate services for:

-   Audio recording
-   Processing pipeline stages
-   Database operations
-   Web interface

Deployment configurations are provided in the repository.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

VERDAD is a project of Public Data Works, developed in collaboration with the Invisible Institute and supported by various organizations working to combat disinformation in Spanish-language media.

## Contact

For questions or support, please open an issue on GitHub or contact the maintainers at [contact information].
