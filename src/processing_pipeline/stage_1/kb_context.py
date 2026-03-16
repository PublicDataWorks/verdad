"""Knowledge Base context retrieval and formatting for Stage 1 detection."""

from openai import OpenAI

from processing_pipeline.constants import KB_SEARCH_MATCH_THRESHOLD
from processing_pipeline.stage_1.constants import (
    KB_STAGE1_CHUNK_SIZE,
    KB_STAGE1_MATCH_COUNT_PER_CHUNK,
)
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
    embeddings = [item.embedding for item in response.data]

    # Search KB for each chunk and deduplicate by entry ID
    seen = {}
    for embedding in embeddings:
        results = supabase_client.search_kb_entries(
            query_embedding=embedding,
            match_threshold=KB_SEARCH_MATCH_THRESHOLD,
            match_count=KB_STAGE1_MATCH_COUNT_PER_CHUNK,
        )
        for entry in results:
            entry_id = entry["id"]
            if entry_id not in seen or entry["similarity"] > seen[entry_id]["similarity"]:
                seen[entry_id] = entry

    if not seen:
        print("[KB Context] No matching KB entries found")
        return None

    # Sort by similarity descending
    entries = sorted(seen.values(), key=lambda e: e["similarity"], reverse=True)
    print(f"[KB Context] Found {len(entries)} unique KB entries")
    return _format_kb_entries(entries)


def _split_into_chunks(text: str, chunk_size: int) -> list[str]:
    chunks = []
    for i in range(0, len(text), chunk_size):
        chunk = text[i:i + chunk_size]
        if chunk:
            chunks.append(chunk)
    return chunks


def _format_kb_entries(entries: list) -> str:
    lines = []
    for entry in entries:
        fact = entry.get("fact", "")
        categories = entry.get("disinformation_categories", [])
        confidence = entry.get("confidence_score", 0)

        block = f"- **Fact**: {fact}\n"
        if categories:
            block += f"  **Categories**: {', '.join(categories)}\n"
        block += f"  **Confidence**: {confidence}%\n"
        lines.append(block)

    return "\n".join(lines)
