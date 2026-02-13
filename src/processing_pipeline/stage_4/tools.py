# WARNING: Do not delete the docstrings of exported functions (search_knowledge_base, upsert_knowledge_entry, deactivate_knowledge_entry).
# They are used by Gemini ADK as tool descriptions.

import json
import os

from openai import OpenAI
from tiktoken import encoding_for_model

from processing_pipeline.constants import GeminiModel
from processing_pipeline.supabase_utils import SupabaseClient


def _get_supabase_client():
    return SupabaseClient(
        supabase_url=os.getenv("SUPABASE_URL"),
        supabase_key=os.getenv("SUPABASE_KEY"),
    )


def _generate_embedding(text: str) -> list[float]:
    openai_api_key = os.getenv("OPENAI_API_KEY")
    if not openai_api_key:
        raise ValueError("OpenAI API key was not set!")

    client = OpenAI(api_key=openai_api_key)
    response = client.embeddings.create(model="text-embedding-3-large", input=text)
    return response.data[0].embedding


def _generate_kb_document(fact: str, related_claim: str | None = None, categories: list[str] | None = None) -> str:
    parts = [f"Fact: {fact}"]
    if related_claim:
        parts.append(f"Related claim: {related_claim}")
    if categories:
        parts.append(f"Categories: {', '.join(categories)}")
    return "\n\n".join(parts)


def search_knowledge_base(query: str, categories: list[str] | None = None, reference_date: str | None = None) -> str:
    """Search the knowledge base for verified facts relevant to a query.

    Args:
        query: The search query describing what facts to look for.
        categories: Optional disinformation categories to filter by.
        reference_date: Optional ISO date string for temporal relevance filtering.

    Returns:
        JSON string of matching knowledge base entries with sources.
    """
    supabase_client = _get_supabase_client()

    # Align query format with stored document format to boost cosine similarity.
    # Stored documents use "Fact: ..." format from _generate_kb_document().
    search_document = _generate_kb_document(query)
    embedding = _generate_embedding(search_document)

    filter_categories = categories if categories else None

    results = supabase_client.search_kb_entries(
        query_embedding=embedding,
        match_threshold=0.3,
        match_count=10,
        filter_categories=filter_categories,
        reference_date=reference_date,
    )

    if not results:
        print(f"  [KB Search] Query: '{query}' — 0 results")
        return json.dumps({"results": [], "message": "No relevant knowledge base entries found."})

    print(f"  [KB Search] Query: '{query}' — {len(results)} results (top similarity: {results[0].get('similarity', 'N/A')})")
    return json.dumps({"results": results, "count": len(results)})


def upsert_knowledge_entry(
    fact: str,
    confidence_score: int,
    categories: list[str],
    keywords: list[str],
    source_url: str,
    source_name: str,
    source_type: str,
    related_claim: str | None = None,
    is_time_sensitive: bool = False,
    valid_from: str | None = None,
    valid_until: str | None = None,
    source_title: str | None = None,
    source_excerpt: str | None = None,
    snippet_id: str | None = None,
) -> str:
    """Create or update a knowledge base entry with a verified fact.

    If a similar entry already exists (similarity > 0.92), creates a new version.
    Otherwise creates a new entry. Only store facts with confidence >= 70.

    Args:
        fact: The verified factual information to store. Must be true.
        confidence_score: Confidence in the fact's accuracy (0-100). Must be >= 70.
        categories: Disinformation categories this fact relates to.
        keywords: Keywords for this fact.
        related_claim: Optional common disinformation claim this fact addresses.
        is_time_sensitive: Whether this fact may become outdated over time.
        valid_from: Optional ISO date when the fact became true.
        valid_until: Optional ISO date when the fact stopped being true.
        source_url: REQUIRED. URL of the primary evidence source. Every KB entry must have an external source.
        source_name: REQUIRED. Name of the source (e.g., Reuters, PolitiFact).
        source_type: REQUIRED. Source tier. Must be one of: tier1_wire_service, tier1_factchecker, tier2_major_news, tier3_regional_news, official_source, other.
        source_title: Title of the source article.
        source_excerpt: Relevant excerpt from the source (50-200 words).
        snippet_id: UUID of the snippet that triggered this KB entry.

    Returns:
        JSON string with the created/updated entry details.
    """
    if confidence_score < 70:
        return json.dumps({"error": "Confidence score must be >= 70 to store in the knowledge base."})

    if not source_url or not source_url.strip():
        return json.dumps({"error": "source_url is required. Every KB entry must have at least one external source."})

    if not source_name or not source_name.strip():
        return json.dumps({"error": "source_name is required. Every KB entry must have at least one external source."})

    if not source_type or not source_type.strip():
        return json.dumps({"error": "source_type is required. Every KB entry must have at least one external source."})

    valid_source_types = {"tier1_wire_service", "tier1_factchecker", "tier2_major_news", "tier3_regional_news", "official_source", "other"}
    if source_type not in valid_source_types:
        return json.dumps({"error": f"Invalid source_type '{source_type}'. Must be one of: {', '.join(sorted(valid_source_types))}"})

    supabase_client = _get_supabase_client()
    category_list = categories or []
    keyword_list = keywords or []

    # Generate embedding for deduplication check
    document = _generate_kb_document(fact, related_claim, category_list)
    embedding = _generate_embedding(document)

    # Check for duplicates
    duplicates = supabase_client.find_duplicate_kb_entries(
        query_embedding=embedding,
        similarity_threshold=0.92,
    )

    if duplicates:
        # Update existing entry (create new version)
        existing_id = duplicates[0]["id"]

        new_entry_data = {
            "fact": fact,
            "confidence_score": confidence_score,
            "disinformation_categories": category_list,
            "keywords": keyword_list,
            "is_time_sensitive": is_time_sensitive,
            "created_by_model": GeminiModel.GEMINI_2_5_FLASH_PREVIEW_09_2025.value,
        }
        if related_claim:
            new_entry_data["related_claim"] = related_claim
        if valid_from:
            new_entry_data["valid_from"] = valid_from
        if valid_until:
            new_entry_data["valid_until"] = valid_until
        if snippet_id:
            new_entry_data["created_by_snippet"] = snippet_id

        entry = supabase_client.supersede_kb_entry(existing_id, new_entry_data)
        action = "updated"
    else:
        # Create new entry
        entry = supabase_client.insert_kb_entry(
            fact=fact,
            confidence_score=confidence_score,
            disinformation_categories=category_list,
            keywords=keyword_list,
            related_claim=related_claim,
            is_time_sensitive=is_time_sensitive,
            valid_from=valid_from,
            valid_until=valid_until,
            created_by_snippet=snippet_id,
            created_by_model=GeminiModel.GEMINI_2_5_FLASH_PREVIEW_09_2025.value,
        )
        action = "created"

    # Add source (required for all entries)
    supabase_client.insert_kb_entry_source(
        kb_entry_id=entry["id"],
        url=source_url,
        source_name=source_name,
        source_type=source_type,
        title=source_title,
        relevant_excerpt=source_excerpt,
    )

    # Generate and store embedding
    try:
        encoding = encoding_for_model("text-embedding-3-large")
        token_count = len(encoding.encode(document))
    except Exception:
        token_count = None

    supabase_client.upsert_kb_entry_embedding(
        kb_entry_id=entry["id"],
        embedded_document=document,
        document_token_count=token_count,
        embedding=embedding,
        model_name="text-embedding-3-large",
    )

    # Record usage
    if snippet_id:
        usage_type = "triggered_update" if duplicates else "triggered_creation"
        supabase_client.record_kb_usage(entry["id"], snippet_id, usage_type)

    return json.dumps(
        {
            "action": action,
            "entry_id": entry["id"],
            "version": entry.get("version", 1),
            "fact": fact,
        }
    )


def deactivate_knowledge_entry(entry_id: str, reason: str) -> str:
    """Deactivate a knowledge base entry that is outdated or incorrect.

    Args:
        entry_id: UUID of the KB entry to deactivate.
        reason: Clear explanation of why this entry is being deactivated.

    Returns:
        JSON string confirming the deactivation.
    """
    supabase_client = _get_supabase_client()
    result = supabase_client.deactivate_kb_entry(entry_id, reason)

    if result:
        return json.dumps({"status": "deactivated", "entry_id": entry_id, "reason": reason})
    else:
        return json.dumps({"error": f"Failed to deactivate entry {entry_id}"})
