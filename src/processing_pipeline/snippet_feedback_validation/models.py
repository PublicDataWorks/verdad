from typing import Literal
from pydantic import BaseModel, Field


class VerificationResult(BaseModel):
    """Verification result for a specific claim."""

    claim: str = Field(description="The specific claim being verified")
    original_assessment: str = Field(description="What Stage 3 concluded about this claim")
    verification_finding: str = Field(description="What web search reveals about this claim")
    is_claim_actually_false: bool = Field(description="Whether the claim is demonstrably false")
    confidence: int = Field(ge=0, le=100, description="Confidence in this verification")


class UserFeedbackAssessment(BaseModel):
    """Assessment of user-provided feedback quality."""

    feedback_quality: Literal["high", "medium", "low"] = Field(
        description="Quality of user-provided feedback"
    )
    feedback_reasoning: str = Field(
        description="Assessment of why user disliked/labeled the snippet"
    )
    appears_adversarial: bool = Field(
        description="Whether feedback appears to be bad-faith or coordinated"
    )


class ValidationDecision(BaseModel):
    """Final validation decision using ML terminology."""

    status: Literal["false_positive", "true_positive", "needs_review"] = Field(
        description="Validation outcome: false_positive (Stage 3 wrong, user right), true_positive (Stage 3 correct, user wrong), needs_review (ambiguous)"
    )
    confidence: int = Field(ge=0, le=100, description="Confidence in this decision")
    primary_reason: str = Field(description="Main reason for this decision")


class ErrorPatternDetected(BaseModel):
    """Classification of the error type Stage 3 made."""

    error_type: Literal[
        "knowledge_cutoff",      # Stage 3 claimed something doesn't exist that was created after cutoff
        "temporal_confusion",    # Stage 3 applied wrong time context
        "insufficient_search",   # Stage 3 didn't search deeply enough
        "misinterpretation",     # Stage 3 misunderstood the content
        "correct_detection",     # No error - Stage 3 was right (use for true_positive)
        "ambiguous",             # Cannot determine error type
    ] = Field(description="Type of error Stage 3 made, if any")
    explanation: str = Field(description="Brief explanation of why this error type was identified")


class FeedbackValidationOutput(BaseModel):
    """Output schema for feedback validation task."""

    # Summary of what's being validated
    original_claim_summary: str = Field(
        description="Brief summary of what Stage 3 flagged as misinformation"
    )
    user_feedback_summary: str = Field(
        description="Brief summary of user feedback and their apparent reasoning"
    )

    # Verification results
    claim_verifications: list[VerificationResult] = Field(
        description="Verification of each major claim from the original analysis"
    )

    # Assessment of user feedback
    user_feedback_assessment: UserFeedbackAssessment

    # Final decision
    validation_decision: ValidationDecision

    # Error pattern classification
    error_pattern: ErrorPatternDetected = Field(
        description="Classification of what type of error Stage 3 made (if any)"
    )

    # Prompt improvement suggestion for Phase 2
    prompt_improvement_suggestion: str | None = Field(
        default=None,
        description="If false_positive, what specific improvement to Stage 3 prompt could prevent this error in future"
    )

    # Thought process (reasoning captured here instead of separate field)
    thought_summaries: str = Field(
        description="Detailed reasoning process including searches performed, evidence found, and how the decision was reached"
    )
