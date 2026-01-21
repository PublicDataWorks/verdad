# Heuristics & Output Schemas

To ensure consistency and high-quality data for researchers and journalists, VERDAD uses structured output schemas (via Pydantic) to govern how the AI pipeline analyzes radio snippets. This approach forces the LLMs to provide specific evidence, bilingual translations, and measurable confidence scores.

## Overview of Heuristics

The VERDAD pipeline operates on a "High Recall, High Precision" heuristic model:

1.  **Stage 1 (High Recall):** Uses Gemini (1.5 or 2.5 Flash) to rapidly screen 5–15 minute audio blocks. It identifies potential disinformation using simplified heuristics to ensure no suspect content is missed.
2.  **Stage 3 (High Precision):** Uses more advanced models to perform a deep-dive analysis on the extracted clips. It applies rigorous validation checks (e.g., "are specific claims quoted?") before the data is finalized.

## Stage 3: In-Depth Analysis Schema

The primary interface for structured data is the `Stage3Output` model. This schema ensures every flagged snippet contains the context, evidence, and emotional metadata required for fact-checking.

### Core Content & Metadata
Every analysis includes full transcriptions and objective summaries in both Spanish and English.

| Field | Type | Description |
| :--- | :--- | :--- |
| `transcription` | `str` | Complete transcription of the audio clip in the original language. |
| `translation` | `str` | Full English translation of the transcription. |
| `title` | `Title` | Bilingual title (Spanish/English) for the snippet. |
| `summary` | `Summary` | Objective bilingual summary of the content. |
| `language` | `Language` | Captures primary language, dialect, and register (formal, colloquial, etc.). |

### Analysis & Claim Validation
VERDAD breaks down disinformation into specific "claims" that are then validated against a checklist.

```python
class Claim(BaseModel):
    quote: str      # Direct quote of the false/misleading claim
    evidence: str   # Evidence demonstrating why the claim is false
    score: int      # Confidence score for this specific claim (0-100)
```

The system employs a **Validation Checklist** heuristic to ensure the LLM's reasoning is defensible:
*   `specific_claims_quoted`: Ensures the AI isn't speaking in generalities.
*   `evidence_provided`: Confirms a factual rebuttal is present.
*   `defensible_to_factcheckers`: A meta-check on the logical consistency of the analysis.

### Confidence Scoring
The system provides granular confidence scores rather than a simple true/false binary.

*   **Overall Score:** A 0–100 rating of the system's confidence in the analysis.
*   **Category Scores:** Each disinformation category (e.g., "Medical," "Election") receives its own confidence score.
*   **Score Adjustments:** If an initial score is modified during the pipeline, the system stores the `initial_score`, `final_score`, and the `adjustment_reason`.

### Emotional & Political Tone
To help researchers understand the *delivery* of disinformation, the schema captures nuance beyond just text.

*   **Emotional Tone:** Analyzes intensity (0–100) and provides `EmotionEvidence` including vocal cues (pitch, speed) and specific patterns.
*   **Political Leaning:** Uses a float scale from `-1.0` (Left) to `1.0` (Right), backed by specific policy positions, rhetoric used, and sources cited.

---

## Usage Example: Accessing Structured Data

When interacting with the Stage 3 output, the data is returned as a JSON object conforming to the `Stage3Output` Pydantic model.

```json
{
  "title": {
    "spanish": "Desinformación sobre el voto por correo",
    "english": "Misinformation regarding mail-in voting"
  },
  "confidence_scores": {
    "overall": 92,
    "categories": [
      {
        "category": "Election Integrity",
        "score": 95
      }
    ]
  },
  "political_leaning": {
    "score": 0.8,
    "evidence": {
      "rhetoric": ["fraude masivo", "votos ilegales"],
      "policy_positions": ["Restriction of mail-in ballots"]
    }
  },
  "emotional_tone": [
    {
      "emotion": { "spanish": "Alarma", "english": "Alarm" },
      "intensity": 85,
      "evidence": {
        "vocal_cues": ["high pitch", "rapid speaking rate"],
        "phrases": ["¡Esto es una emergencia!"]
      }
    }
  ]
}
```

## Safety Heuristics
During the processing of content that may contain sensitive or harmful speech, the pipeline uses specific `SafetySettings` to ensure the AI can analyze "Hate Speech" or "Dangerous Content" without being blocked by default provider filters, allowing researchers to see the raw data while maintaining a record of the content's harm category.

| Category | Threshold |
| :--- | :--- |
| `HARM_CATEGORY_HATE_SPEECH` | `BLOCK_NONE` (Logged for research) |
| `HARM_CATEGORY_DANGEROUS_CONTENT` | `BLOCK_NONE` |
| `HARM_CATEGORY_CIVIC_INTEGRITY` | `BLOCK_NONE` |
