# Introduction

VERDAD is an open-source platform engineered to identify, analyze, and track potential disinformation within radio broadcasts. While social media platforms often receive the bulk of content moderation attention, radio remains a significant, yet under-scrutinized, vector for misinformation—particularly within immigrant and non-English speaking communities.

The platform provides journalists, researchers, and fact-checkers with a systematic way to monitor audio streams, generate AI-powered analyses of suspected claims, and collaborate on verifying or debunking content in real-time.

## Project Mission

The primary objectives of VERDAD are:

1.  **Visibility:** To provide actionable data for trustworthy newsrooms to disseminate timely fact-checks and accurate narratives.
2.  **Investigation:** To support long-term research into regional and temporal trends of disinformation campaigns.
3.  **Automation at Scale:** To leverage multimodal AI models to process thousands of hours of audio that would be impossible for human teams to monitor manually.

## The AI Pipeline Architecture

VERDAD operates through a multi-stage pipeline orchestrated by **Prefect**. The system moves from raw audio ingestion to structured, human-readable intelligence.

### Stage 1: Detection & Transcription
The system continuously records audio from configured stations. It uses **OpenAI Whisper** for high-fidelity speech-to-text (ASR) and **Google Gemini** (1.5 Flash or 2.5 Flash) to perform a rapid initial screening. This stage identifies "snippets" of interest based on simplified heuristics to ensure high recall.

### Stage 2: Audio Clipping
Once a segment is flagged, the system extracts the specific audio clip. It automatically includes configurable "context windows" (e.g., 90 seconds before and 60 seconds after the segment) to ensure analysts understand the full scope of the conversation.

### Stage 3: In-Depth Analysis
This is the core "intelligence" phase. The platform generates a comprehensive analysis of the snippet, including:
*   **Bi-lingual Metadata:** Titles, summaries, and explanations in both the original language (e.g., Spanish or Arabic) and English.
*   **Claim Extraction:** Specific quotes of false/misleading claims paired with evidence-based rebuttals.
*   **Sentiment & Tone:** Detection of vocal cues, emotional intensity (0-100), and the cultural impact of the delivery.
*   **Political Leaning:** A calculated score (-1.0 to 1.0) indicating the political direction of the content based on policy positions and rhetoric.

### Stage 4 & 5: Review and Embedding
Final AI reviews ensure the analysis is defensible to professional fact-checkers. The data is then vectorized (embedded) for similarity searching, allowing users to find related disinformation patterns across different dates or stations.

## Structured Output for Researchers

For developers and data scientists, VERDAD provides structured JSON output via its API and database. The analysis follows a strict schema to ensure consistency across thousands of snippets:

```json
{
  "transcription": "Original audio text...",
  "title": {
    "spanish": "Título del segmento",
    "english": "Segment Title"
  },
  "analysis": {
    "claims": [
      {
        "quote": "The specific misleading statement",
        "evidence": "Why this claim is factually incorrect",
        "score": 85
      }
    ],
    "political_leaning": {
      "score": 0.75,
      "explanation": "Analysis of rhetoric used..."
    }
  },
  "emotional_tone": {
    "intensity": 90,
    "vocal_cues": ["shouting", "urgent tempo"]
  }
}
```

## Collaborative Review Interface

The system is not a "black box." It includes an interactive front-end where experts can:
*   **Review:** Listen to snippets alongside their AI-generated transcripts.
*   **Validate:** Upvote or downvote the accuracy of AI labels.
*   **Annotate:** Add custom labels and discuss findings via a built-in comment system (powered by Liveblocks and Supabase).
*   **Notify:** Real-time integrations with Slack and Email ensure that high-priority disinformation is flagged to the team immediately.

## Tech Stack Summary

*   **Orchestration:** Prefect (running on Fly.io)
*   **LLMs:** Google Gemini (1.5 and 2.5 Pro & Flash models)
*   **ASR:** OpenAI Whisper
*   **Backend:** Node.js (Express), TypeScript, Python
*   **Database:** PostgreSQL (Supabase) with Vector support
*   **Notifications:** Resend (Email), Slack Webhooks
