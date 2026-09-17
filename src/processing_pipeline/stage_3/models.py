import copy
import re
import unicodedata
from datetime import date
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field

from processing_pipeline.kb_sources import is_http_url, parse_iso_date, url_key
from processing_pipeline.temporal_context import BREAKING_NEWS_TIERS


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
    event_date: str | None = Field(
        default=None,
        description=(
            "ISO date (YYYY-MM-DD) of the event the claim is about (when it allegedly happened), or null when the "
            "claim is not about a datable event"
        ),
    )


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
    url_observed_in_tools: bool | None = Field(
        default=None,
        description=(
            "Set by the pipeline, not the model: whether the URL of a contradicts_claim result was returned by a "
            "search or fetch tool in the same session (null when not checked)"
        ),
    )
    publication_date_source: Literal["model", "tool"] | None = Field(
        default=None,
        description=(
            "Set by the pipeline, not the model: 'model' when publication_date came from the analysis, 'tool' when "
            "the pipeline filled it from the date the search tool returned for this URL (null when not checked)"
        ),
    )


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


# Hosts and paths that can never be "a source that contradicts the claim": a search-results page, a WHOIS
# lookup, a web cache, or a site's front page. The model has cited every one of these as contradicting evidence.
_SEARCH_PAGE_HOSTS = ("google.", "bing.com", "duckduckgo.com", "search.yahoo.", "yandex.", "baidu.com")
_NON_ARTICLE_HOSTS = ("whois.", "who.is", "webcache.googleusercontent.com", "archive.org/search")
_LOCALE_SEGMENT_RE = re.compile(r"^[a-z]{2}(?:[-_][a-z]{2})?$", re.IGNORECASE)


def is_article_url(url) -> bool:
    """True when ``url`` points at a specific page that could contradict a claim, not a front page or a search.

    Rejected: non-http URLs; search-engine result pages (``google.com/search?q=…``); WHOIS and cache lookups;
    and front pages, i.e. an empty path or one made only of locale segments (``https://apnews.com/``,
    ``https://www.microsoft.com/en-us``). A front page shows today's headlines, never the fact the model claims
    it contains.
    """
    if not is_http_url(url):
        return False
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower().removeprefix("www.")
    path = parts.path or ""
    if any(host == h.rstrip(".") or host.startswith(h) or ("." + h) in ("." + host) for h in _SEARCH_PAGE_HOSTS):
        if path.rstrip("/") in ("", "/search", "/s", "/html") or path.startswith("/search"):
            return False
    if any(h in host or h in (host + path) for h in _NON_ARTICLE_HOSTS):
        return False
    segments = [seg for seg in path.split("/") if seg]
    if not segments or all(_LOCALE_SEGMENT_RE.match(seg) for seg in segments):
        return False
    return True


def latest_claim_event_date(analysis: dict | None) -> date | None:
    """The latest ``claims[].event_date`` the model recorded (None when no claim carries a parseable date).

    Search results are not linked to individual claims, so the gate cannot tell which claim a contradicting
    source refutes. The latest event date is the conservative boundary: a source older than the most recent
    claimed event could only refute an earlier claim, and the verdict rests on all of them.
    """
    if not isinstance(analysis, dict):
        return None
    scores = analysis.get("confidence_scores")
    claims = (((scores or {}).get("analysis") or {}).get("claims") or []) if isinstance(scores, dict) else []
    dates = [parse_iso_date(c.get("event_date")) for c in claims if isinstance(c, dict)]
    dates = [d for d in dates if d is not None]
    return max(dates) if dates else None


def fill_publication_dates(verification_evidence: dict | None, observed_url_dates: dict[str, str] | None) -> int:
    """Fill ``publication_date`` (in place) from what the search tool reported for each URL.

    ``observed_url_dates`` maps ``url_key`` -> ISO date for every result URL a tool returned with a date. A result
    whose model-written date is missing or unparseable gets the tool's date and ``publication_date_source='tool'``;
    a result that already carries a parseable date is marked ``'model'``. Returns the number of dates filled.
    """
    if not isinstance(verification_evidence, dict) or observed_url_dates is None:
        return 0
    filled = 0
    for search in verification_evidence.get("searches_performed") or []:
        if not isinstance(search, dict):
            continue
        for result in search.get("results") or []:
            if not isinstance(result, dict):
                continue
            if parse_iso_date(result.get("publication_date")) is not None:
                result["publication_date_source"] = "model"
                continue
            tool_date = observed_url_dates.get(url_key(result.get("url")))
            if tool_date and parse_iso_date(tool_date) is not None:
                result["publication_date"] = tool_date
                result["publication_date_source"] = "tool"
                filled += 1
    return filled


def _contradicting_results(verification_evidence: dict | None):
    """Yield every recorded search result marked contradicts_claim that carries an http(s) URL."""
    if not isinstance(verification_evidence, dict):
        return
    for search in verification_evidence.get("searches_performed") or []:
        if not isinstance(search, dict):
            continue
        for result in search.get("results") or []:
            if not isinstance(result, dict):
                continue
            if result.get("relevance_to_claim") == "contradicts_claim" and is_http_url(result.get("url")):
                yield result


def url_was_observed(url, observed_urls: set[str]) -> bool:
    """True when ``url`` names a page in ``observed_urls`` (a set of ``url_key`` values); see ``url_key``."""
    return url_key(url) in observed_urls


def _result_counts(
    result: dict,
    observed_urls: set[str] | None,
    earliest_event_date: date | None,
    require_date: bool,
) -> bool:
    """Whether one contradicts_claim result is admissible as contradicting evidence under every active rule."""
    if not is_article_url(result.get("url")):
        return False
    if observed_urls is not None and not url_was_observed(result.get("url"), observed_urls):
        return False
    if observed_urls is None and result.get("url_observed_in_tools") is False:
        # Stage 4 has no tool record of its own, but Stage 3 stored its verdict on this URL: a URL no tool
        # returned stays inadmissible when the reviewer re-runs the gate on the stored evidence.
        return False
    published = parse_iso_date(result.get("publication_date"))
    if earliest_event_date is not None and published is not None and published < earliest_event_date:
        return False
    if require_date and published is None:
        return False
    return True


def has_contradicting_evidence(
    verification_evidence: dict | None,
    observed_urls: set[str] | None = None,
    earliest_event_date: date | None = None,
    require_date: bool = False,
) -> bool:
    """True when at least one recorded search result contradicts the claim and is admissible as evidence.

    A result is admissible when it is marked contradicts_claim, carries an http(s) URL that is an article
    (``is_article_url``: not a front page, search page or WHOIS lookup), and passes the optional rules:

    ``observed_urls`` is the set of ``url_key`` values for every URL the search and fetch tools returned in
    the same session. When it is given, a contradicting result only counts if its URL is in that set: the
    model can invent a plausible URL (a reuters.com article about an election that never happened) and mark
    it contradicts_claim, and such a URL never came back from a tool. When it is ``None`` (Stage 4, which has
    no Stage 3 tool record; the evaluation harness reading stored records; offline callers) any http(s) URL
    counts, as before.

    ``earliest_event_date`` is the boundary date (callers pass ``latest_claim_event_date``: results are not linked
    to claims, so the most recent claimed event is the conservative choice). A source published before it
    cannot refute it (a 2024 fact-check cannot contradict a 2026 ruling). Undated sources still count, so the
    URL-only decision stands; the publication date is not required unless ``require_date``.

    A result Stage 3 already marked ``url_observed_in_tools = False`` never counts, even when ``observed_urls``
    is ``None``, so Stage 4 cannot restore a score Stage 3 capped for an invented URL.
    """
    for result in _contradicting_results(verification_evidence):
        if _result_counts(result, observed_urls, earliest_event_date, require_date):
            return True
    return False


def _mark_observed(verification_evidence: dict | None, observed_urls: set[str]) -> None:
    """Record on each contradicting result (in place) whether a tool returned its URL, for the audit trail."""
    for result in _contradicting_results(verification_evidence):
        result["url_observed_in_tools"] = url_was_observed(result.get("url"), observed_urls)


def _cap_scores(confidence_scores: dict, cap: int) -> tuple:
    original_overall = confidence_scores.get("overall")
    categories = [c for c in confidence_scores.get("categories") or [] if isinstance(c, dict)]
    original_categories = [{"category": c.get("category"), "score": c.get("score")} for c in categories]
    if isinstance(original_overall, (int, float)):
        confidence_scores["overall"] = min(original_overall, cap)
    for category in categories:
        if isinstance(category.get("score"), (int, float)):
            category["score"] = min(category["score"], cap)
    return original_overall, original_categories


def breaking_news_cap(hours_since_recording) -> int | None:
    """The H.1 cap for a recording of this age (20 within 24 h, 30 within 72 h), or None when none applies."""
    try:
        hours = float(hours_since_recording)
    except (TypeError, ValueError):
        return None
    for max_hours, max_score in BREAKING_NEWS_TIERS:
        if hours <= max_hours:
            return max_score
    return None


def apply_evidence_caps(
    analysis: dict,
    verification_evidence: dict | None = None,
    observed_urls: set[str] | None = None,
    hours_since_recording: float | str | None = None,
) -> dict:
    """Clamp confidence scores that are not backed by evidence.

    Returns a deep copy of ``analysis``. When a cap applies, ``confidence_scores.overall`` and every
    ``confidence_scores.categories[].score`` are clamped to the cap, a machine note is appended to both
    explanation languages, and the copy carries an ``evidence_gate`` dict (reasons, cap, pre-cap scores) that
    callers store in ``grounding_metadata``. When nothing applies, the copy carries
    ``evidence_gate = {"applied": False}``.

    Two caps, in order:

    1. ``EVIDENCE_CAP_MAX_SCORE`` (40) when the analysis admits it has no evidence, or asserts falsity /
       ``verified_false`` without an admissible contradicting source (see ``has_contradicting_evidence``).
    2. The breaking-news cap (prompt rule H.1, ``BREAKING_NEWS_TIERS``: 20 within 24 h of recording, 30 within
       72 h) when ``hours_since_recording`` is given and inside the window, the verdict rests on falsity, and no
       admissible contradicting source carries a publication date. Within the window an undated page cannot show
       that it post-dates the event, and "no coverage yet" is the failure mode this rule exists for.

    ``verification_evidence`` defaults to ``analysis["verification_evidence"]`` (Stage 3 output shape).
    Stage 4 passes the Stage 3 record explicitly because the reviewer output has no structured evidence.

    ``observed_urls`` (``url_key`` values of every URL the session's search and fetch tools returned) makes a
    contradicting result count only when a tool actually returned its URL; see ``has_contradicting_evidence``.
    When given and the evidence is the copy's own, each contradicting result is also marked with
    ``url_observed_in_tools`` so the outcome is auditable in the stored record.
    """
    result = copy.deepcopy(analysis)
    confidence_scores = result.get("confidence_scores")
    if not isinstance(confidence_scores, dict):
        result["evidence_gate"] = {"applied": False}
        return result

    if verification_evidence is None:
        verification_evidence = result.get("verification_evidence")
        if observed_urls is not None:
            _mark_observed(verification_evidence, observed_urls)

    # A previous run's note (e.g. Stage 3's, echoed by the Stage 4 reviewer) must not be judged or kept
    explanation = result.get("explanation")
    if isinstance(explanation, dict):
        for language in ("english", "spanish"):
            if language in explanation:
                explanation[language] = _without_gate_note(explanation[language])

    event_date = latest_claim_event_date(result)
    status = confidence_scores.get("verification_status")
    falsity_verdict = status == "verified_false" or asserts_falsity(result)

    reasons = []
    if status in UNVERIFIED_STATUSES:
        reasons.append(f"verification_status is '{status}'")
    evidenced = has_contradicting_evidence(verification_evidence, observed_urls, event_date)
    if status == "verified_false" and not evidenced:
        reasons.append(
            "verification_status is 'verified_false' but no search result with a URL is marked contradicts_claim"
        )
    if asserts_falsity(result) and not evidenced:
        reasons.append(
            "the analysis asserts the content is fabricated/false but no search result with a URL is "
            "marked contradicts_claim"
        )
    if reasons and not evidenced:
        # Say which rule disqualified the contradicting URLs on record, since the reasons above read as
        # "no contradicting result" and the analyst will see one in the evidence.
        recorded = list(_contradicting_results(verification_evidence))
        if recorded and not any(is_article_url(r.get("url")) for r in recorded):
            reasons.append("the only contradicting URLs are front pages, search pages or lookups, not articles")
        elif recorded and observed_urls is not None and not any(
            url_was_observed(r.get("url"), observed_urls) for r in recorded
        ):
            reasons.append("contradicting URL not returned by any search or fetch tool in this session")
        elif recorded and event_date is not None:
            reasons.append(
                f"every contradicting source is dated before the latest claimed event ({event_date.isoformat()})"
            )

    cap = EVIDENCE_CAP_MAX_SCORE
    if not reasons:
        breaking_cap = breaking_news_cap(hours_since_recording)
        dated = has_contradicting_evidence(verification_evidence, observed_urls, event_date, require_date=True)
        if breaking_cap is not None and falsity_verdict and not dated:
            overall = confidence_scores.get("overall")
            if isinstance(overall, (int, float)) and overall > breaking_cap:
                cap = breaking_cap
                reasons.append(
                    f"recording is {hours_since_recording} hours old (breaking news window) and no contradicting "
                    "source carries a publication date"
                )

    if not reasons:
        result["evidence_gate"] = {"applied": False}
        return result

    original_overall, original_categories = _cap_scores(confidence_scores, cap)

    note_en = f"{EVIDENCE_GATE_NOTE_PREFIX} Confidence capped at {cap} by the pipeline because " + "; ".join(reasons) + "."
    note_es = (
        f"{EVIDENCE_GATE_NOTE_PREFIX} La confianza fue limitada a {cap} por el sistema "
        f"(sin evidencia suficiente: {'; '.join(reasons)})."
    )
    if isinstance(explanation, dict):
        explanation["english"] = f"{explanation.get('english') or ''}\n\n{note_en}".strip()
        explanation["spanish"] = f"{explanation.get('spanish') or ''}\n\n{note_es}".strip()

    result["evidence_gate"] = {
        "applied": True,
        "cap": cap,
        "reasons": reasons,
        "original_overall": original_overall,
        "original_categories": original_categories,
        "note": note_en,
    }
    return result
