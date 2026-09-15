"""Knowledge Base context retrieval and formatting for Stage 1 detection."""

from openai import OpenAI

from processing_pipeline.kb_sources import is_http_url, source_is_usable
from processing_pipeline.stage_1.constants import (
    KB_STAGE1_CHUNK_SIZE,
    KB_STAGE1_MATCH_COUNT_PER_CHUNK,
    KB_STAGE1_MIN_CONFIDENCE,
    STAGE_1_KB_MATCH_THRESHOLD,
)
from processing_pipeline.processing_utils import normalize_embedding
from processing_pipeline.supabase_utils import SupabaseClient


def retrieve_kb_context(
    supabase_client: SupabaseClient,
    openai_client: OpenAI,
    transcription: str,
) -> str | None:
    if not transcription:
        return None

    # Split transcription into chunks to cover all topics in the broadcast
    chunks = _split_into_chunks(transcription, KB_STAGE1_CHUNK_SIZE)
    print(f"[KB Context] Split transcription ({len(transcription)} chars) into {len(chunks)} chunks")

    # Batch-embed all chunks in a single API call
    response = openai_client.embeddings.create(model="text-embedding-3-large", input=chunks)
    embeddings = [normalize_embedding(item.embedding) for item in response.data]

    # Search KB for each chunk and deduplicate by entry ID
    seen = {}
    for embedding in embeddings:
        results = supabase_client.search_kb_entries(
            query_embedding=embedding,
            match_threshold=STAGE_1_KB_MATCH_THRESHOLD,
            match_count=KB_STAGE1_MATCH_COUNT_PER_CHUNK,
            min_confidence=KB_STAGE1_MIN_CONFIDENCE,
        )
        for entry in results:
            entry_id = entry["id"]
            if entry_id not in seen or entry["similarity"] > seen[entry_id]["similarity"]:
                seen[entry_id] = entry

    entries = select_trustworthy_entries(seen.values())
    if not entries:
        print(f"[KB Context] No trustworthy KB entries found ({len(seen)} matched before source filtering)")
        return None

    print(f"[KB Context] Found {len(entries)} trustworthy KB entries ({len(seen)} matched)")
    return _format_kb_entries(entries)


def _split_into_chunks(text: str, chunk_size: int) -> list[str]:
    chunks = []
    for i in range(0, len(text), chunk_size):
        chunk = text[i:i + chunk_size]
        if chunk:
            chunks.append(chunk)
    return chunks


def is_pipeline_authored(entry: dict) -> bool:
    return str(entry.get("created_by_model") or "").lower().startswith("gemini")


def is_trustworthy_entry(entry: dict, min_confidence: int = KB_STAGE1_MIN_CONFIDENCE) -> bool:
    """A Stage 1 KB fact needs high confidence and a real, non-'other' source; pipeline-written facts also need a date.

    ``created_by_model`` is only present once the updated search_kb_entries SQL is deployed; without it every
    entry is treated as human-authored for the dating rule.
    """
    if (entry.get("confidence_score") or 0) < min_confidence:
        return False
    sources = [s for s in entry.get("sources") or [] if source_is_usable(s)]
    if not sources:
        return False
    if is_pipeline_authored(entry) and not any(s.get("publication_date") for s in sources):
        return False
    return True


def select_trustworthy_entries(entries) -> list[dict]:
    trustworthy = [entry for entry in entries if is_trustworthy_entry(entry)]
    return sorted(trustworthy, key=lambda e: e["similarity"], reverse=True)


def _format_source(source: dict) -> str:
    name = source.get("source_name") or source.get("url")
    date = source.get("publication_date") or "undated"
    return f"{name} — {source['url']} ({date})"


def _format_kb_entries(entries: list) -> str:
    lines = []
    for entry in entries:
        fact = entry.get("fact", "")
        categories = entry.get("disinformation_categories", [])
        confidence = entry.get("confidence_score", 0)
        sources = [s for s in entry.get("sources") or [] if is_http_url(s.get("url"))]

        block = f"- **Fact**: {fact}\n"
        if categories:
            block += f"  **Categories**: {', '.join(categories)}\n"
        block += f"  **Confidence**: {confidence}%\n"
        for source in sources:
            block += f"  **Source**: {_format_source(source)}\n"
        lines.append(block)

    return "\n".join(lines)
