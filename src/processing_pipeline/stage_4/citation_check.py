import copy
import json

from processing_pipeline.kb_sources import url_key, urls_in_text
from processing_pipeline.stage_3.models import (
    EVIDENCE_CAP_MAX_SCORE,
    EVIDENCE_GATE_NOTE_PREFIX,
    asserts_falsity,
    cap_scores,
    is_article_url,
    strip_pipeline_note,
    url_was_observed,
)
from processing_pipeline.stage_4 import constants

CITATION_CHECK_NOTE_PREFIX = "[Citation check]"
NOTE_URL_LIMIT = 3


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


def _retrieval(tool_record: dict) -> dict:
    """What the session's tools put in front of the model, by kind."""
    searches = [s for s in tool_record.get("searches") or [] if isinstance(s, dict)]
    fetches = [f for f in tool_record.get("fetches") or [] if isinstance(f, dict)]
    kb_searches = [k for k in tool_record.get("kb_searches") or [] if isinstance(k, dict)]
    return {
        "searches": len(searches),
        "searches_with_results": sum(s.get("status") == "results_found" for s in searches),
        "pages_read": sum(f.get("status") == "ok" for f in fetches),
        "kb_curated_sources": sum(len(k.get("curated_source_urls") or []) for k in kb_searches),
    }


def _falsity_verdict(response: dict) -> bool:
    """The reviewer's own verdict, judged without the evidence gate's note (the citation note is already gone)."""
    status = (response.get("confidence_scores") or {}).get("verification_status")
    if status == "verified_false":
        return True
    explanation = response.get("explanation")
    if isinstance(explanation, dict):
        explanation = {
            language: strip_pipeline_note(text, EVIDENCE_GATE_NOTE_PREFIX) if isinstance(text, str) else text
            for language, text in explanation.items()
        }
    return asserts_falsity({**response, "explanation": explanation})


def _listed(urls: list[str], more_en: bool) -> str:
    shown = ", ".join(urls[:NOTE_URL_LIMIT])
    rest = len(urls) - NOTE_URL_LIMIT
    if rest <= 0:
        return shown
    return f"{shown} and {rest} more" if more_en else f"{shown} y {rest} más"


def check_stage_4_citations(
    response: dict, stage_4_grounding_metadata: str | None, stage_3_evidence, enforce: bool | None = None
) -> tuple[dict, dict]:
    """Judge the review against the Stage 4 tool record.

    Returns a deep copy of ``response`` and the ``stage_4_citation_check`` dict. Three rules, each a reason:

    1. the review's visible text cites an article URL that neither a Stage 4 tool returned nor the Stage 3
       record holds;
    2. (VER-393) the web researcher's prose cites such a URL: the reviewer scored on invented research;
    3. (VER-369 item 2) the review asserts fabrication / ``verified_false`` while nothing was retrieved in this
       session: no web search returned results, no page was read, no curated KB source came back. The Stage 3
       record is deliberately not consulted here: the evidence gate judges it, this rule asks what the review
       itself retrieved.

    Only article URLs count in 1 and 2 (``is_article_url``): a front page or a search page is not a citation.
    With ``enforce`` (default ``CITATION_CHECK_CAPS``) any reason clamps the scores to ``EVIDENCE_CAP_MAX_SCORE``
    and appends a bilingual explanation note; ``original_*`` are the scores as received, i.e. already 40 when
    the evidence gate ran first (its own ``original_*`` hold the pre-gate values).
    """
    if enforce is None:
        enforce = constants.CITATION_CHECK_CAPS
    metadata = json.loads(stage_4_grounding_metadata) if stage_4_grounding_metadata else {}
    tool_record = metadata.get("stage_4_tool_record") or {}
    admissible = set(tool_record.get("observed_urls") or [])
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
    unobserved = sorted({c["url"] for c in cited if not c["observed"] and is_article_url(c["url"])})
    web_research_unobserved = sorted(
        {
            url
            for url in urls_in_text(metadata.get("web_research"))
            if is_article_url(url) and not url_was_observed(url, admissible)
        }
    )
    retrieval = _retrieval(tool_record)

    reasons = []  # (english, spanish)
    if unobserved:
        reasons.append(
            (
                "the review cites URLs that no search or read tool returned in this session: "
                + _listed(unobserved, True),
                "la revisión cita URLs que ninguna herramienta de búsqueda o lectura devolvió en esta sesión: "
                + _listed(unobserved, False),
            )
        )
    if web_research_unobserved:
        reasons.append(
            (
                "the web research cites URLs that no search or read tool returned: "
                + _listed(web_research_unobserved, True),
                "la investigación web cita URLs que ninguna herramienta de búsqueda o lectura devolvió: "
                + _listed(web_research_unobserved, False),
            )
        )
    nothing_retrieved = not (
        retrieval["searches_with_results"] or retrieval["pages_read"] or retrieval["kb_curated_sources"]
    )
    if nothing_retrieved and _falsity_verdict(result):
        reasons.append(
            (
                "the review asserts the content is fabricated/false but no web search returned results, no page "
                f"was read and no curated knowledge-base source came back in this session ({retrieval['searches']} searches)",
                "la revisión afirma que el contenido es fabricado/falso pero ninguna búsqueda web devolvió "
                "resultados, no se leyó ninguna página y ninguna fuente curada de la base de conocimiento "
                f"apareció en esta sesión ({retrieval['searches']} búsquedas)",
            )
        )

    check = {
        "applied": bool(reasons) and enforce,
        "reasons": [en for en, _ in reasons],
        "cited": cited,
        "unobserved": unobserved,
        "web_research_unobserved": web_research_unobserved,
        "retrieval": retrieval,
    }
    if not check["applied"]:
        return result, check

    cap = EVIDENCE_CAP_MAX_SCORE
    if isinstance(result.get("confidence_scores"), dict):
        check["original_overall"], check["original_categories"] = cap_scores(result["confidence_scores"], cap)
    note_en = (
        f"{CITATION_CHECK_NOTE_PREFIX} Confidence limited to {cap} by the pipeline because "
        + "; ".join(en for en, _ in reasons)
        + "."
    )
    note_es = (
        f"{CITATION_CHECK_NOTE_PREFIX} La confianza está limitada a {cap} por el sistema porque "
        + "; ".join(es for _, es in reasons)
        + "."
    )
    if isinstance(explanation, dict):
        explanation["english"] = f"{explanation.get('english') or ''}\n\n{note_en}".strip()
        explanation["spanish"] = f"{explanation.get('spanish') or ''}\n\n{note_es}".strip()
    check["note"] = note_en
    return result, check
