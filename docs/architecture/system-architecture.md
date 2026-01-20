# System Architecture

## Architectural Overview

VERDAD is architected as a distributed, multi-stage processing pipeline optimized for analyzing continuous audio streams. The system leverages a decoupled architecture where heavy-duty AI processing is orchestrated by **Prefect**, managed by **Fly.io**, and synchronized through **Supabase (PostgreSQL)**.

The system is designed to transform raw radio broadcasts into structured, searchable, and actionable disinformation intelligence through five distinct processing stages.


## Pipeline Orchestration

The pipeline is managed using **Prefect**, which handles task scheduling, retries, and state management. The infrastructure is deployed on **Fly.io** using a "Process Group" pattern.

### Process Groups and Deployment
Instead of running a monolithic service, VERDAD uses environment variables to determine the role of a specific instance. The `FLY_PROCESS_GROUP` variable dictates which pipeline stage a worker handles.

**Example Configuration (`fly.toml` or Env):**
```bash
# To run a worker dedicated to Stage 1 detection
FLY_PROCESS_GROUP="initial_disinformation_detection"
```

The available process groups correspond to the primary stages and administrative tasks:


## Data Flow: The 5-Stage Pipeline

### Stage 1: Initial Detection & Transcription
**Primary Models:** Gemini 1.5 Flash or 2.5 Flash, OpenAI Whisper.

The system consumes full audio recordings (5-15 minutes). 
1. **Transcription:** OpenAI Whisper generates a timestamped transcript.
2. **Screening:** Gemini (1.5 Flash or 2.5 Flash) applies high-recall heuristics to flag segments that potentially contain disinformation.
3. **Output:** A set of candidate timestamps and a preliminary "confidence score" for further investigation.

**Note:** Gemini 2.5 models offer improved performance and lower costs compared to 1.5 models.

### Stage 2: Audio Clipping
**Process:**
This stage extracts the specific audio segments flagged in Stage 1. It automatically includes a configurable "context window" (defaulting to 90 seconds before and 60 seconds after the hit) to ensure analysts have sufficient background information.

### Stage 3: In-Depth Analysis
**Primary Model:** Gemini 1.5 Pro or 2.5 Pro (Multimodal).

This is the core analytical engine. The system performs a nuanced evaluation of the clip, producing a structured Pydantic-validated object. Newer 2.5 Pro models provide improved analysis quality. 

**Public Data Interface (`Stage3Output`):**
The analysis includes:

### Stage 4: Analysis Review
**Process:**
A secondary LLM pass (or human-in-the-loop) reviews the findings from Stage 3. It checks for consistency, validates that quotes are accurate, and ensures the reasoning is defensible to professional fact-checkers.

### Stage 5: Vector Embedding
**Process:**
Finalized analyses are converted into vector embeddings. These are stored in the database to enable similarity searches, helping researchers identify recurring disinformation narratives across different stations and timeframes.


## Backend Services & Collaboration

### Database and Real-time Sync (Supabase)
Supabase serves as the central state machine. 

### Collaboration Layer (Liveblocks)
The human element of VERDAD—journalists and researchers—interacts via a collaborative frontend.

### Notifications (Resend & Slack)
The system includes an integrated `emailService` and `slackService` to alert researchers of new mentions or critical findings.


## Error Handling and Monitoring

- **Sentry:** Integrated across the Python pipeline and Node.js server for real-time error tracking.
- **Safety Settings:** All Gemini LLM calls utilize custom safety configurations to ensure the model doesn't block content necessary for disinformation analysis. These include:
  - `HARM_CATEGORY_HATE_SPEECH`: Required to analyze hate speech in broadcasts
  - `HARM_CATEGORY_HARASSMENT`: Allows analysis of harassment content
  - `HARM_CATEGORY_DANGEROUS_CONTENT`: Necessary for analyzing dangerous rhetoric
  - `HARM_CATEGORY_CIVIC_INTEGRITY`: Critical for election and political integrity content
  - `HARM_CATEGORY_SEXUALLY_EXPLICIT`: Allows analysis of explicit content when relevant

```python
# Internal Safety Logic - All set to BLOCK_NONE
SafetySetting(
    category=HarmCategory.HARM_CATEGORY_HATE_SPEECH,
    threshold=HarmBlockThreshold.BLOCK_NONE,
)
SafetySetting(
    category=HarmCategory.HARM_CATEGORY_CIVIC_INTEGRITY,
    threshold=HarmBlockThreshold.BLOCK_NONE,
)
# ... and others (see src/processing_pipeline/processing_utils.py)
```

## Infrastructure Usage for Developers

To run a local worker for a specific stage, ensure your `.env` is configured and execute:

```bash
python src/processing_pipeline/main.py
```
*Note: The script will automatically detect the `FLY_PROCESS_GROUP` and start the corresponding Prefect deployment.*

---

## User Interface and Feedback Loop

VERDAD's front-end provides several key screens and user interaction flows:

- **Feed Screen:** An infinitely scrolling stack of cards, each representing a snippet of suspected disinformation. Users can filter by radio station, state, or label.
- **Individual Snippet Screen:** Focused on a single snippet, with related snippets ranked by similarity.
- **Public View:** Accessible without login, showing transcribed/translated text and audio, but no labels or comments.

**User Interactions:**
- Review AI-flagged content
- Affirm or add labels
- Add free-form comments
- Upvote existing labels
- Engage in discussions about snippets

This feedback is integrated into the iterative refinement process, helping to improve detection heuristics and prompt accuracy over time.
