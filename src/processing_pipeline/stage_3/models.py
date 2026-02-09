from typing import Literal
from pydantic import BaseModel, Field


class Title(BaseModel):
    spanish: str = Field(description="Title of the snippet in Spanish")
    english: str = Field(description="Title of the snippet in English")


class Summary(BaseModel):
    spanish: str = Field(description="Summary of the snippet in Spanish")
    english: str = Field(description="Summary of the snippet in English")


class Explanation(BaseModel):
    spanish: str = Field(description="Explanation of the analysis findings in Spanish")
    english: str = Field(description="Explanation of the analysis findings in English")


class DisinformationCategory(BaseModel):
    spanish: str = Field(description="Disinformation category in Spanish")
    english: str = Field(description="Disinformation category in English")


class Language(BaseModel):
    primary_language: str = Field(description="Primary language of the audio (e.g., Spanish, Arabic)")
    dialect: str = Field(description="Specific dialect or regional variation")
    register_: str = Field(alias="register", description="Language register (formal, informal, colloquial, slang)")


class Context(BaseModel):
    before: str = Field(description="Part of the audio clip transcription that precedes the snippet")
    before_en: str = Field(description="Translation of the 'before' part into English")
    after: str = Field(description="Part of the audio clip transcription that follows the snippet")
    after_en: str = Field(description="Translation of the 'after' part into English")
    main: str = Field(description="The transcription of the snippet itself")
    main_en: str = Field(description="Translation of the 'main' part into English")


class Claim(BaseModel):
    quote: str = Field(description="Direct quote of the false or misleading claim")
    evidence: str = Field(description="Evidence demonstrating why the claim is false")
    score: int = Field(description="Confidence score for this specific claim")


class ValidationChecklist(BaseModel):
    specific_claims_quoted: bool
    evidence_provided: bool
    scoring_falsity: bool
    defensible_to_factcheckers: bool
    consistent_explanations: bool
    uncertain_claims_scored_low: bool


class ScoreAdjustments(BaseModel):
    initial_score: int
    final_score: int
    adjustment_reason: str


class Analysis(BaseModel):
    claims: list[Claim]
    validation_checklist: ValidationChecklist
    score_adjustments: ScoreAdjustments


class CategoryScore(BaseModel):
    category: str = Field(description="Name of the disinformation category")
    score: int = Field(ge=0, le=100, description="Confidence score for this category, ranging from 0 to 100")


class ConfidenceScores(BaseModel):
    overall: int = Field(ge=0, le=100, description="Overall confidence score of the analysis, ranging from 0 to 100")
    verification_status: Literal["verified_false", "verified_true", "uncertain", "insufficient_evidence"] = Field(
        description="Overall verification status based on evidence quality"
    )
    analysis: Analysis
    categories: list[CategoryScore]


class EmotionText(BaseModel):
    spanish: str
    english: str


class EmotionEvidence(BaseModel):
    vocal_cues: list[str] = Field(description="Specific vocal characteristics observed")
    phrases: list[str] = Field(description="Direct quotes demonstrating the emotion")
    patterns: list[str] = Field(description="Recurring emotional patterns or themes")


class EmotionImpact(BaseModel):
    credibility: str
    audience_reception: str
    cultural_context: str


class EmotionExplanation(BaseModel):
    spanish: str
    english: str
    impact: EmotionImpact


class EmotionalToneItem(BaseModel):
    emotion: EmotionText
    intensity: int = Field(description="Intensity of the emotion, ranging from 0 to 100")
    evidence: EmotionEvidence
    explanation: EmotionExplanation


class PoliticalEvidence(BaseModel):
    policy_positions: list[str] = Field(description="Explicit policy positions stated")
    arguments: list[str] = Field(description="Specific arguments made")
    rhetoric: list[str] = Field(description="Key phrases and rhetoric used")
    sources: list[str] = Field(description="Sources or authorities cited")
    solutions: list[str] = Field(description="Solutions proposed")


class PoliticalScoreAdjustments(BaseModel):
    initial_score: float
    final_score: float
    reasoning: str


class PoliticalExplanation(BaseModel):
    spanish: str
    english: str
    score_adjustments: PoliticalScoreAdjustments


class PoliticalLeaning(BaseModel):
    score: float = Field(ge=-1.0, le=1.0, description="Political leaning score, ranging from -1.0 to 1.0")
    evidence: PoliticalEvidence
    explanation: PoliticalExplanation


class SearchResult(BaseModel):
    url: str = Field(description="Full URL of the source")
    source_name: str = Field(description="Name of the publication or website (e.g., Reuters, AP News, BBC)")
    source_type: Literal[
        "tier1_wire_service", "tier1_factchecker", "tier2_major_news",
        "tier3_regional_news", "official_source", "other"
    ] = Field(description="Classification of source reliability tier")
    publication_date: str | None = Field(description="Publication date in ISO 8601 format (YYYY-MM-DD), or null if not available")
    title: str = Field(description="Title or headline of the article/page")
    relevant_excerpt: str = Field(description="Direct quote from the source relevant to the claim (50-200 words)")
    relevance_to_claim: Literal["supports_claim", "contradicts_claim", "provides_context", "inconclusive"] = Field(
        description="How this result relates to the claim being verified"
    )
    content_fetched: bool = Field(default=False, description="Whether the full article content was fetched")


class SearchPerformed(BaseModel):
    query: str = Field(description="The exact search query used")
    search_intent: str = Field(description="What claim or fact this search was attempting to verify")
    result_status: Literal["results_found", "no_results", "results_inconclusive"] = Field(
        description="Whether the search returned actionable results"
    )
    results: list[SearchResult] = Field(default_factory=list, description="Individual search results")


class VerificationSummary(BaseModel):
    total_searches: int = Field(description="Total number of web searches performed")
    claims_contradicted: int = Field(description="Number of claims found to be false based on search evidence")
    claims_unverifiable: int = Field(description="Number of claims that could not be verified")
    key_findings: str = Field(description="Narrative summary of the most important verification findings")


class VerificationEvidence(BaseModel):
    searches_performed: list[SearchPerformed] = Field(description="Record of all web searches")
    verification_summary: VerificationSummary = Field(description="Summary of verification activities")


class Stage3Output(BaseModel):
    """Main model for Stage 3 output."""

    transcription: str = Field(description="Transcription of the entire audio clip in the original language")
    translation: str = Field(description="Translation of the transcription into English")
    title: Title = Field(description="Descriptive title of the snippet")
    summary: Summary = Field(description="Objective summary of the snippet")
    explanation: Explanation = Field(description="Detailed explanation of the analysis findings, including why content is scored as disinformation or verified as accurate")
    disinformation_categories: list[DisinformationCategory] = Field(
        description="Disinformation categories that the snippet belongs to"
    )
    keywords_detected: list[str] = Field(
        description="Specific words or phrases that triggered the flag, in original language"
    )
    language: Language
    context: Context
    confidence_scores: ConfidenceScores
    emotional_tone: list[EmotionalToneItem]
    political_leaning: PoliticalLeaning
    thought_summaries: str = Field(
        description="A summary of your reasoning process, key observations, and analytical steps taken during the analysis"
    )
    verification_evidence: VerificationEvidence = Field(
        description="Complete documentation of all web searches performed during fact-checking"
    )
