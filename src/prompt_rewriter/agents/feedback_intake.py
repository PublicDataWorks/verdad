"""
Feedback Intake Agent

Analyzes user feedback to classify intent and extract actionable information.
This is the first agent in the pipeline, transforming raw user feedback
into structured data for the Research Agent.
"""

import json
import logging
from uuid import UUID

from ..config import PromptRewriterConfig
from ..models import FeedbackAnalysis, FeedbackEvent, FeedbackIntent
from .base import BaseAgent

logger = logging.getLogger(__name__)

FEEDBACK_CLASSIFICATION_PROMPT = """You are analyzing user feedback on a misinformation detection system.
The system analyzes audio snippets from radio broadcasts and identifies potential misinformation.

A user has provided feedback on a snippet analysis. Your job is to:
1. Classify the intent of the feedback
2. Extract any specific claims the user is disputing
3. Determine what the user believes the correct interpretation should be
4. Identify which parts of the analysis pipeline may need adjustment

## Snippet Context
Title: {title}
Summary: {summary}
Categories detected: {categories}
Original transcription: {transcription}

## User Feedback
Feedback type: {feedback_type}
Content: {feedback_content}

## Classification Instructions

Classify the feedback intent as one of:
- factual_error: The analysis contains incorrect factual claims or misidentifies something as misinformation when it's true (or vice versa)
- missing_context: The analysis lacks important context that would change the interpretation
- wrong_category: The disinformation category assignment is incorrect
- false_positive: This content was incorrectly flagged as misinformation
- false_negative: This content should have been flagged but wasn't
- unclear_explanation: The explanation is confusing or poorly written
- translation_error: The Spanish/English translation is incorrect
- other: Feedback doesn't fit other categories

## Response Format
Respond with a JSON object:
{{
    "intent": "<intent_classification>",
    "intent_confidence": <0.0-1.0>,
    "extracted_claim": "<the specific claim being disputed, if any>",
    "user_correction": "<what the user believes is correct, if stated>",
    "affected_prompt_stages": [<list of stage numbers that may need updating, e.g., [1, 3]>],
    "priority": "<low|medium|high|critical>",
    "reasoning": "<brief explanation of your classification>"
}}

Priority guidelines:
- critical: Dangerous misinformation being spread as truth, or truth being labeled as dangerous misinformation
- high: Clear factual errors that could mislead users
- medium: Missing context or unclear explanations
- low: Minor issues, translation tweaks, category refinements
"""


class FeedbackIntakeAgent(BaseAgent[FeedbackEvent, FeedbackAnalysis]):
    """
    Analyzes user feedback to determine intent and extract actionable information.

    Input: FeedbackEvent (raw user feedback)
    Output: FeedbackAnalysis (structured classification and extracted claims)
    """

    name = "feedback_intake"

    def __init__(self, config: PromptRewriterConfig | None = None):
        super().__init__(config)

    async def run(self, feedback: FeedbackEvent) -> FeedbackAnalysis:
        """
        Analyze the feedback and return structured classification.
        """
        # Fetch snippet context from database
        snippet = await self._get_snippet(feedback.snippet_id)

        if not snippet:
            logger.warning(f"Snippet {feedback.snippet_id} not found")
            return FeedbackAnalysis(
                intent=FeedbackIntent.OTHER,
                intent_confidence=0.5,
                reasoning="Could not find snippet context",
            )

        # Build the classification prompt
        prompt = FEEDBACK_CLASSIFICATION_PROMPT.format(
            title=snippet.get("title", "Unknown"),
            summary=snippet.get("summary", "No summary available"),
            categories=", ".join(snippet.get("disinformation_categories", [])),
            transcription=snippet.get("transcription", "")[:1000],  # Truncate
            feedback_type=feedback.feedback_type,
            feedback_content=feedback.content or "No content provided",
        )

        # Call LLM for classification
        response = await self.call_llm(
            prompt=prompt,
            model=self.config.feedback_intake_model,
            temperature=0.3,  # Lower temperature for classification
        )

        # Parse the response
        return self._parse_response(response)

    async def _get_snippet(self, snippet_id: UUID) -> dict | None:
        """Fetch snippet details from database."""
        try:
            result = (
                self.supabase.table("snippets")
                .select("id, title, summary, transcription, disinformation_categories")
                .eq("id", str(snippet_id))
                .single()
                .execute()
            )
            return result.data
        except Exception as e:
            logger.error(f"Error fetching snippet {snippet_id}: {e}")
            return None

    def _parse_response(self, response: str) -> FeedbackAnalysis:
        """Parse LLM response into FeedbackAnalysis."""
        try:
            # Extract JSON from response (handle markdown code blocks)
            json_str = response
            if "```json" in response:
                json_str = response.split("```json")[1].split("```")[0]
            elif "```" in response:
                json_str = response.split("```")[1].split("```")[0]

            data = json.loads(json_str.strip())

            return FeedbackAnalysis(
                intent=FeedbackIntent(data.get("intent", "other")),
                intent_confidence=float(data.get("intent_confidence", 0.5)),
                extracted_claim=data.get("extracted_claim"),
                user_correction=data.get("user_correction"),
                affected_prompt_stages=data.get("affected_prompt_stages", [1, 3]),
                priority=data.get("priority", "medium"),
                reasoning=data.get("reasoning"),
            )

        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.error(f"Failed to parse LLM response: {e}")
            logger.debug(f"Raw response: {response}")

            # Return a default analysis on parse failure
            return FeedbackAnalysis(
                intent=FeedbackIntent.OTHER,
                intent_confidence=0.3,
                reasoning=f"Failed to parse LLM response: {e}",
            )
