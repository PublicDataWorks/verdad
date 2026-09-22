import json
import re
from datetime import date
from typing import Literal

from pydantic import BaseModel, ValidationError

from processing_pipeline.kb_sources import is_http_url
from processing_pipeline.stage_3.models import has_contradicting_evidence, mark_observed

_EVIDENCE_BLOCK_RE = re.compile(r"```evidence\s*\n(.*?)```", re.DOTALL)


class EvidenceResult(BaseModel):
    """One source from the web researcher's fenced evidence block: the Stage 3 SearchResult fields the gate reads."""

    url: str
    source_name: str = ""
    source_type: Literal[
        "tier1_wire_service", "tier1_factchecker", "tier2_major_news", "tier3_regional_news", "official_source", "other"
    ] = "other"
    publication_date: str | None = None
    title: str = ""
    relevance_to_claim: Literal["supports_claim", "contradicts_claim", "provides_context", "inconclusive"]


def parse_evidence_block(web_research: str | None) -> dict | None:
    """``{"results": [...], "dropped": n}`` from the report's block; None when there is no block or it is not JSON."""
    match = _EVIDENCE_BLOCK_RE.search(web_research or "")
    if not match:
        return None
    try:
        raw = json.loads(match.group(1))
    except ValueError:
        return None
    entries = raw.get("results") if isinstance(raw, dict) else None
    if not isinstance(entries, list):
        return None
    results, dropped = [], 0
    for entry in entries:
        try:
            result = EvidenceResult.model_validate(entry)
        except ValidationError:
            dropped += 1
            continue
        if not is_http_url(result.url):
            dropped += 1
            continue
        results.append(result.model_dump())
    return {"results": results, "dropped": dropped}


def stage_4_evidence(
    stage_4_grounding_metadata: str | None, event_date: date | None
) -> tuple[dict | None, dict | None]:
    """(record in the Stage 3 shape for the gate, dict to store) from the researcher's block; (None, None) without one.

    Each contradicting result is marked ``url_observed_in_tools`` against the session's tool record, so a URL
    no tool returned never counts; ``admissible_contradicting`` in the stored dict says whether one contradicting
    result passes the gate's URL and date rules (``has_contradicting_evidence``).
    """
    metadata = json.loads(stage_4_grounding_metadata) if stage_4_grounding_metadata else {}
    evidence = parse_evidence_block(metadata.get("web_research"))
    if evidence is None:
        return None, None
    record = {"searches_performed": [{"results": evidence["results"]}]} if evidence["results"] else None
    if record:
        mark_observed(record, set((metadata.get("stage_4_tool_record") or {}).get("observed_urls") or []))
    evidence["admissible_contradicting"] = has_contradicting_evidence(record, None, event_date)
    return record, evidence


def combine_evidence(stage_3_evidence: dict | None, stage_4_record: dict | None) -> dict | None:
    """The Stage 3 record as is when Stage 4 reported nothing, else both records' searches for one gate pass."""
    if not stage_4_record:
        return stage_3_evidence
    searches = list((stage_3_evidence or {}).get("searches_performed") or [])
    return {"searches_performed": searches + stage_4_record["searches_performed"]}
