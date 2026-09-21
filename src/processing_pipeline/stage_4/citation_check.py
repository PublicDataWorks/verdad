import copy
import json

from processing_pipeline.kb_sources import url_key, urls_in_text
from processing_pipeline.stage_3.models import EVIDENCE_CAP_MAX_SCORE, cap_scores, strip_pipeline_note, url_was_observed
from processing_pipeline.stage_4 import constants

CITATION_CHECK_NOTE_PREFIX = "[Citation check]"


def _stage_3_recorded_urls(stage_3_evidence) -> set[str]:
    """url_key of every Stage 3 result URL, minus those Stage 3 already marked as never returned by a tool."""
    keys = set()
    for search in (stage_3_evidence or {}).get("searches_performed") or []:
        for result in (search.get("results") or []) if isinstance(search, dict) else []:
            # None = Stage 3 did not judge this result (pre-PR #98 rows, non-contradicting results): admissible
            if isinstance(result, dict) and result.get("url_observed_in_tools") is not False:
                keys.add(url_key(result.get("url")))
    keys.discard("")
    return keys


def _visible_texts(response: dict) -> list[tuple[str, str]]:
    """(field, text) for every reviewer field an analyst reads."""
    texts = []
    for field in ("explanation", "summary"):
        value = response.get(field)
        if isinstance(value, dict):
            texts.extend((f"{field}.{language}", text) for language, text in value.items() if isinstance(text, str))
    if isinstance(response.get("thought_summaries"), str):
        texts.append(("thought_summaries", response["thought_summaries"]))
    confidence_scores = response.get("confidence_scores")
    analysis = confidence_scores.get("analysis") if isinstance(confidence_scores, dict) else None
    for i, claim in enumerate((analysis.get("claims") or []) if isinstance(analysis, dict) else []):
        if isinstance(claim, dict) and isinstance(claim.get("evidence"), str):
            texts.append((f"claims[{i}].evidence", claim["evidence"]))
    return texts


def check_stage_4_citations(
    response: dict, stage_4_grounding_metadata: str | None, stage_3_evidence, enforce: bool | None = None
) -> tuple[dict, dict]:
    """Find URLs in the review's visible text that neither a Stage 4 tool returned nor the Stage 3 record holds.

    Returns a deep copy of ``response`` and the ``stage_4_citation_check`` dict. With ``enforce`` (default
    ``CITATION_CHECK_CAPS``) an unobserved URL clamps the scores to ``EVIDENCE_CAP_MAX_SCORE`` and appends a
    bilingual explanation note; ``original_*`` are the scores as received, i.e. already 40 when the evidence gate
    ran first (its own ``original_*`` hold the pre-gate values). URLs found only in the web researcher's prose
    are recorded, never capped: analysts do not see that text.
    """
    if enforce is None:
        enforce = constants.CITATION_CHECK_CAPS
    metadata = json.loads(stage_4_grounding_metadata) if stage_4_grounding_metadata else {}
    admissible = set((metadata.get("stage_4_tool_record") or {}).get("observed_urls") or [])
    admissible |= _stage_3_recorded_urls(stage_3_evidence)

    result = copy.deepcopy(response)
    explanation = result.get("explanation")
    if isinstance(explanation, dict):
        for language in ("english", "spanish"):
            if language in explanation:
                explanation[language] = strip_pipeline_note(explanation[language], CITATION_CHECK_NOTE_PREFIX)

    cited = []
    for where, text in _visible_texts(result):
        for url in urls_in_text(text):
            cited.append({"url": url, "where": where, "observed": url_was_observed(url, admissible)})
    unobserved = sorted({c["url"] for c in cited if not c["observed"]})
    check = {
        "applied": bool(unobserved) and enforce,
        "cited": cited,
        "unobserved": unobserved,
        "web_research_unobserved": [
            url for url in urls_in_text(metadata.get("web_research")) if not url_was_observed(url, admissible)
        ],
    }
    if not check["applied"]:
        return result, check

    cap = EVIDENCE_CAP_MAX_SCORE
    if isinstance(result.get("confidence_scores"), dict):
        check["original_overall"], check["original_categories"] = cap_scores(result["confidence_scores"], cap)
    listed = ", ".join(unobserved)
    note_en = (
        f"{CITATION_CHECK_NOTE_PREFIX} Confidence capped at {cap} by the pipeline because the review cites URLs "
        f"that no search or read tool returned in this session: {listed}."
    )
    note_es = (
        f"{CITATION_CHECK_NOTE_PREFIX} La confianza fue limitada a {cap} por el sistema porque la revisión cita "
        f"URLs que ninguna herramienta de búsqueda o lectura devolvió en esta sesión: {listed}."
    )
    if isinstance(explanation, dict):
        explanation["english"] = f"{explanation.get('english') or ''}\n\n{note_en}".strip()
        explanation["spanish"] = f"{explanation.get('spanish') or ''}\n\n{note_es}".strip()
    check["note"] = note_en
    return result, check
