from pydantic import BaseModel, Field

from processing_pipeline.stage_3.models import (
    ConfidenceScores,
    DisinformationCategory,
    Explanation,
    Language,
    PoliticalLeaning,
    Summary,
    Title,
)


class ReviewAnalysisOutput(BaseModel):
    translation: str = Field(description="Translation of the transcription into English")
    title: Title
    summary: Summary
    explanation: Explanation
    disinformation_categories: list[DisinformationCategory]
    keywords_detected: list[str] = Field(description="Specific words or phrases that triggered the flag, in original language")
    language: Language
    confidence_scores: ConfidenceScores
    political_leaning: PoliticalLeaning
    thought_summaries: str = Field(
        description="A summary of your reasoning process, key observations, and analytical steps taken during the review"
    )
