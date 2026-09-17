import copy
import re
import unicodedata
from typing import Literal

from pydantic import BaseModel, Field

from processing_pipeline.kb_sources import is_http_url


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
    register: str = Field(description="Language register (formal, informal, colloquial, slang)")


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
        "tier1_wire_service", "tier1_factchecker", "tier2_major_news", "tier3_regional_news", "official_source", "other"
    ] = Field(description="Classification of source reliability tier")
    publication_date: str | None = Field(
        description="Publication date in ISO 8601 format (YYYY-MM-DD), or null if not available"
    )
    title: str = Field(description="Title or headline of the article/page")
    relevant_excerpt: str = Field(description="Direct quote from the source relevant to the claim (50-200 words)")
    relevance_to_claim: Literal["supports_claim", "contradicts_claim", "provides_context", "inconclusive"] = Field(
        description="How this result relates to the claim being verified"
    )
    content_fetched: bool = Field(default=False, description="Whether the full article content was fetched")


class SearchPerformed(BaseModel):
    query: str = Field(description="The exact search query used")
    search_intent: str = Field(description="What claim or fact this search was attempting to verify")
    result_status: Literal["results_found", "no_results", "results_inconclusive", "search_failed"] = Field(
        description=(
            "Whether the search returned actionable results. Use search_failed when the tool reported "
            "failed=true (error/timeout): a failed search is not evidence of anything."
        )
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
    explanation: Explanation = Field(
        description="Detailed explanation of the analysis findings, including why content is scored as disinformation or verified as accurate"
    )
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


# --- Deterministic evidence gate -------------------------------------------------------------------
#
# The analyst feed only shows snippets with confidence_scores.overall >= 95, and the model's `overall`
# is otherwise unconstrained. These caps make sure that an analysis which admits it has no evidence
# (or asserts that something is fabricated without a single contradicting source) can never reach it.

EVIDENCE_CAP_MAX_SCORE = 40
UNVERIFIED_STATUSES = frozenset({"insufficient_evidence", "uncertain"})
FALSITY_TERMS = (
    "fabricat",
    "fabricado",
    "ficticio",
    "fictional",
    "did not happen",
    "no ocurrió",
    "no existe",
    "does not exist",
    "invented",
    "inventado",
    "never happened",
    "never occurred",
    "nunca ocurrió",
    "nunca sucedió",
    "hoax",
    "made up",
    "is false",
    "are false",
    "es falso",
    "es falsa",
    "son falsos",
    "son falsas",
    "mentira",
    "fake news",
    "debunked",
    "desmentid",
    "untrue",
)
EVIDENCE_GATE_NOTE_PREFIX = "[Evidence gate]"


def _fold(text: str) -> str:
    """Lowercase and strip accents so 'ocurrió' and 'ocurrio' compare equal."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


# Terms match at a word start only ("prefabricated" is not "fabricated") and do not count when negated:
# "not fabricated", "no fabricated content detected", "no evidence of fabrication", "isn't fictional",
# "no fue inventado" and "Fabricated content: none" all describe absent fabrication, not an assertion of it.
# A negation only reaches a term within the same sentence and across at most two intervening words ("This never
# happened and is fabricated" asserts fabrication; "Is it real? No. The story was fabricated." does too), and a
# "label: value" only negates when the value is a bare negation ("Fabricated claim: no source confirms it" asserts
# fabrication).
# Terms that need more than a plain prefix match: "the crowd was made up of supporters" describes composition,
# not fabrication, so "made up" only counts when it is not followed by "of".
FALSITY_TERM_PATTERNS = {
    "made up": r"made up(?!\s+of\b)",
}
_FALSITY_TERM_RE = re.compile(
    r"\b(?:" + "|".join(FALSITY_TERM_PATTERNS.get(term) or re.escape(_fold(term)) for term in FALSITY_TERMS) + ")"
)
_NEGATED_BEFORE_RE = re.compile(
    r"\b(?:not|no|non|never|nothing|neither|nor|without|\w+n't|nunca|ningun\w*|nada|tampoco|ni)"
    r"(?:[^\w.;!?\n]+\w+){0,2}?[^\w.;!?\n]*$"
)
_NEGATED_AFTER_RE = re.compile(
    r"^\w*(?:\s+\w+){0,2}\s*:\s*(?:none|no|n/a|ninguno|ninguna|not(?:\s+\w+)?)\b\s*(?:[.;,!?)\]]|$)"
)
_NEGATION_WINDOW = 60
_GATE_NOTE_RE = re.compile(r"\s*" + re.escape(EVIDENCE_GATE_NOTE_PREFIX) + r"[^\n]*")


def _bilingual_texts(value) -> list[str]:
    if isinstance(value, dict):
        return [v for v in value.values() if isinstance(v, str)]
    if isinstance(value, str):
        return [value]
    return []


def mentions_falsity(text: str) -> bool:
    """True when ``text`` contains a non-negated FALSITY_TERM (case- and accent-insensitive)."""
    folded = _fold(text or "")
    for match in _FALSITY_TERM_RE.finditer(folded):
        start, end = match.span()
        before = folded[:start][-_NEGATION_WINDOW:]
        after = folded[end:][:_NEGATION_WINDOW]
        if _NEGATED_BEFORE_RE.search(before) or _NEGATED_AFTER_RE.match(after):
            continue
        return True
    return False


def _without_gate_note(text) -> str:
    """Drop a note appended by an earlier run so a re-review neither keeps a stale note nor gets two."""
    return _GATE_NOTE_RE.sub("", text if isinstance(text, str) else "").strip()


def asserts_falsity(analysis: dict) -> bool:
    """True when any disinformation category or explanation text asserts that something is fabricated."""
    texts = list(_bilingual_texts(analysis.get("explanation")))
    for category in analysis.get("disinformation_categories") or []:
        texts.extend(_bilingual_texts(category))
    # Each field is judged on its own: a negation at the end of one explanation must not neutralise a
    # "Fabricated Event" category that follows it.
    return any(mentions_falsity(text) for text in texts)


def has_contradicting_evidence(verification_evidence: dict | None) -> bool:
    """True when at least one recorded search result contradicts the claim and carries an http(s) URL.

    The publication date is not required: Stage 3 often cannot read one off the page, and an undated
    contradicting source is still a source the analyst can open. Date normalisation is asked of the prompt.
    """
    if not isinstance(verification_evidence, dict):
        return False
    for search in verification_evidence.get("searches_performed") or []:
        if not isinstance(search, dict):
            continue
        for result in search.get("results") or []:
            if not isinstance(result, dict):
                continue
            if result.get("relevance_to_claim") == "contradicts_claim" and is_http_url(result.get("url")):
                return True
    return False


def apply_evidence_caps(analysis: dict, verification_evidence: dict | None = None) -> dict:
    """Clamp confidence scores that are not backed by evidence.

    Returns a deep copy of ``analysis``. When a cap applies, ``confidence_scores.overall`` and every
    ``confidence_scores.categories[].score`` are clamped to ``EVIDENCE_CAP_MAX_SCORE``, a machine note is
    appended to both explanation languages, and the copy carries an ``evidence_gate`` dict (reasons, cap,
    pre-cap scores) that callers store in ``grounding_metadata``. When nothing applies, the copy carries
    ``evidence_gate = {"applied": False}``.

    ``verification_evidence`` defaults to ``analysis["verification_evidence"]`` (Stage 3 output shape).
    Stage 4 passes the Stage 3 record explicitly because the reviewer output has no structured evidence.
    """
    result = copy.deepcopy(analysis)
    confidence_scores = result.get("confidence_scores")
    if not isinstance(confidence_scores, dict):
        result["evidence_gate"] = {"applied": False}
        return result

    if verification_evidence is None:
        verification_evidence = result.get("verification_evidence")

    # A previous run's note (e.g. Stage 3's, echoed by the Stage 4 reviewer) must not be judged or kept
    explanation = result.get("explanation")
    if isinstance(explanation, dict):
        for language in ("english", "spanish"):
            if language in explanation:
                explanation[language] = _without_gate_note(explanation[language])

    reasons = []
    status = confidence_scores.get("verification_status")
    if status in UNVERIFIED_STATUSES:
        reasons.append(f"verification_status is '{status}'")
    evidenced = has_contradicting_evidence(verification_evidence)
    if status == "verified_false" and not evidenced:
        reasons.append(
            "verification_status is 'verified_false' but no search result with a URL is marked contradicts_claim"
        )
    if asserts_falsity(result) and not evidenced:
        reasons.append(
            "the analysis asserts the content is fabricated/false but no search result with a URL is "
            "marked contradicts_claim"
        )

    if not reasons:
        result["evidence_gate"] = {"applied": False}
        return result

    original_overall = confidence_scores.get("overall")
    categories = [c for c in confidence_scores.get("categories") or [] if isinstance(c, dict)]
    original_categories = [{"category": c.get("category"), "score": c.get("score")} for c in categories]
    if isinstance(original_overall, (int, float)):
        confidence_scores["overall"] = min(original_overall, EVIDENCE_CAP_MAX_SCORE)
    for category in categories:
        if isinstance(category.get("score"), (int, float)):
            category["score"] = min(category["score"], EVIDENCE_CAP_MAX_SCORE)

    note_en = (
        f"{EVIDENCE_GATE_NOTE_PREFIX} Confidence capped at {EVIDENCE_CAP_MAX_SCORE} by the pipeline because "
        + "; ".join(reasons)
        + "."
    )
    note_es = (
        f"{EVIDENCE_GATE_NOTE_PREFIX} La confianza fue limitada a {EVIDENCE_CAP_MAX_SCORE} por el sistema "
        f"(sin evidencia suficiente: {'; '.join(reasons)})."
    )
    if isinstance(explanation, dict):
        explanation["english"] = f"{explanation.get('english') or ''}\n\n{note_en}".strip()
        explanation["spanish"] = f"{explanation.get('spanish') or ''}\n\n{note_es}".strip()

    result["evidence_gate"] = {
        "applied": True,
        "cap": EVIDENCE_CAP_MAX_SCORE,
        "reasons": reasons,
        "original_overall": original_overall,
        "original_categories": original_categories,
        "note": note_en,
    }
    return result
