# WARNING: Do not delete the docstrings of exported functions (search_knowledge_base, upsert_knowledge_entry, deactivate_knowledge_entry).
# They are used by Gemini ADK as tool descriptions.

import os

from google.adk.tools.tool_context import ToolContext
from openai import OpenAI
from tiktoken import encoding_for_model

from processing_pipeline.constants import (
    KB_DEDUP_SIMILARITY_THRESHOLD,
    KB_SEARCH_MATCH_THRESHOLD,
    GeminiModel,
)
from processing_pipeline.kb_sources import (
    VALID_SOURCE_TYPES,
    contains_http_url,
    is_http_url,
    parse_iso_date,
    url_appears_in_text,
)
from processing_pipeline.processing_utils import normalize_embedding
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
    return normalize_embedding(response.data[0].embedding)


def _generate_kb_document(fact: str, related_claim: str | None = None, categories: list[str] | None = None) -> str:
    parts = [f"Fact: {fact}"]
    if related_claim:
        parts.append(f"Related claim: {related_claim}")
    if categories:
        parts.append(f"Categories: {', '.join(categories)}")
    return "\n\n".join(parts)


def search_knowledge_base(query: str, categories: list[str] | None = None, reference_date: str | None = None) -> dict:
    """Search the knowledge base for verified facts relevant to a query.

    Args:
        query: The search query describing what facts to look for.
        categories: Optional disinformation categories to filter by.
        reference_date: Optional ISO date string for temporal relevance filtering.

    Returns:
        Dictionary of matching knowledge base entries with sources.
    """
    supabase_client = _get_supabase_client()

    # Align query format with stored document format to boost cosine similarity.
    # Stored documents use "Fact: ..." format from _generate_kb_document().
    search_document = _generate_kb_document(query)
    embedding = _generate_embedding(search_document)

    results = supabase_client.search_kb_entries(
        query_embedding=embedding,
        match_threshold=KB_SEARCH_MATCH_THRESHOLD,
        match_count=10,
        filter_categories=categories,
        reference_date=reference_date,
    )

    if not results:
        print(f"  [KB Search] Query: '{query}' — 0 results")
        return {"results": [], "message": "No relevant knowledge base entries found."}

    print(f"  [KB Search] Query: '{query}' — {len(results)} results (top similarity: {results[0].get('similarity', 'N/A')})")
    return {"results": results, "count": len(results)}

def _error(message: str) -> dict:
    return {"status": "error", "error_message": message}


def validate_kb_source(
    source_url: str,
    source_name: str,
    source_type: str,
    publication_date: str | None,
    web_research: str | None,
) -> str | None:
    """Return an error message when the source does not qualify as KB evidence, else None.

    ``web_research`` is the web researcher's output for this session; when it is available the URL must
    appear in it (the model may only cite what it actually found). When it is unavailable the check is
    skipped and logged.
    """
    if not is_http_url(source_url):
        return "source_url must be an absolute http(s) URL with a host name (e.g. https://apnews.com/article/...)."
    if not source_name or not source_name.strip():
        return "source_name is required. Every KB entry must have at least one external source."
    if source_type not in VALID_SOURCE_TYPES:
        return f"Invalid source_type '{source_type}'. Must be one of: {', '.join(sorted(VALID_SOURCE_TYPES))}"
    if source_type == "other":
        return (
            "source_type 'other' cannot be the sole source of a KB entry. Cite a wire service, fact-checker, "
            "major/regional news outlet or official source."
        )
    if publication_date is not None and parse_iso_date(publication_date) is None:
        return f"publication_date '{publication_date}' is not an ISO date (YYYY-MM-DD)."
    if not web_research:
        print("  [KB Upsert] web research text unavailable in session state; skipping URL provenance check")
    elif not url_appears_in_text(source_url, web_research):
        return (
            f"source_url '{source_url}' does not appear in this session's web research. "
            "Only cite URLs that were actually returned by the search or read tools."
        )
    return None


def _web_research_text(tool_context: ToolContext | None) -> str | None:
    value = tool_context.state.get("web_research") if tool_context is not None else None
    return value if isinstance(value, str) and value.strip() else None


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
    publication_date: str | None = None,
    snippet_id: str | None = None,
    tool_context: ToolContext | None = None,
) -> dict:
    """Create or update a knowledge base entry with a verified fact.

    If a similar entry already exists (similarity > 0.92), creates a new version, unless the existing active
    entry has a higher confidence score (then nothing is written and the response says so).
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
        source_type: REQUIRED. Source tier. Must be one of: tier1_wire_service, tier1_factchecker,
            tier2_major_news, tier3_regional_news, official_source. 'other' is rejected as a sole source.
        source_title: Title of the source article.
        source_excerpt: Relevant excerpt from the source (50-200 words).
        publication_date: Publication date of the source in ISO format (YYYY-MM-DD), if known.
        snippet_id: UUID of the snippet that triggered this KB entry.

    Returns:
        Dictionary with status and details of the created or updated KB entry.
    """
    if confidence_score < 70:
        return _error("Confidence score must be >= 70 to store in the knowledge base.")

    source_error = validate_kb_source(
        source_url, source_name, source_type, publication_date, _web_research_text(tool_context)
    )
    if source_error:
        return _error(source_error)

    supabase_client = _get_supabase_client()

    # Generate embedding for deduplication check
    document = _generate_kb_document(fact, related_claim, categories)
    embedding = _generate_embedding(document)

    # Check for duplicates
    duplicates = supabase_client.find_duplicate_kb_entries(
        query_embedding=embedding,
        similarity_threshold=KB_DEDUP_SIMILARITY_THRESHOLD,
    )

    if duplicates:
        existing = duplicates[0]
        existing_id = existing["id"]
        existing_confidence = existing.get("confidence_score") or 0
        if existing.get("status", "active") == "active" and existing_confidence > confidence_score:
            # The kb_entry_status enum has no 'pending' value, so a lower-confidence rewrite is dropped, not stored.
            print(
                f"  [KB Upsert] Not superseding entry {existing_id} (confidence {existing_confidence}) with a "
                f"lower-confidence fact ({confidence_score}); skipping"
            )
            return {
                "status": "skipped",
                "action": "kept_existing",
                "entry_id": existing_id,
                "existing_confidence_score": existing_confidence,
                "message": "An existing active entry with higher confidence already covers this fact; nothing written.",
            }

        # Update existing entry (create new version)
        new_entry_data = {
            "fact": fact,
            "confidence_score": confidence_score,
            "disinformation_categories": categories,
            "keywords": keywords,
            "is_time_sensitive": is_time_sensitive,
            "created_by_model": GeminiModel.GEMINI_2_5_PRO.value,
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
            disinformation_categories=categories,
            keywords=keywords,
            related_claim=related_claim,
            is_time_sensitive=is_time_sensitive,
            valid_from=valid_from,
            valid_until=valid_until,
            created_by_snippet=snippet_id,
            created_by_model=GeminiModel.GEMINI_2_5_PRO.value,
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
        publication_date=publication_date,
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

    return {
        "status": "success",
        "action": action,
        "entry_id": entry["id"],
        "version": entry.get("version", 1),
        "fact": fact,
    }


def deactivate_knowledge_entry(entry_id: str, reason: str) -> dict:
    """Deactivate a knowledge base entry that is outdated or incorrect.

    Args:
        entry_id: UUID of the KB entry to deactivate.
        reason: Clear explanation of why this entry is being deactivated. Must include the http(s) URL of the
            source that shows the entry is outdated or incorrect.

    Returns:
        Dictionary with status and details of the deactivation.
    """
    if not contains_http_url(reason):
        return _error(
            "reason must cite the http(s) URL of the evidence showing the entry is outdated or incorrect."
        )

    supabase_client = _get_supabase_client()
    result = supabase_client.deactivate_kb_entry(entry_id, reason)

    if result:
        return {"status": "deactivated", "entry_id": entry_id, "reason": reason}
    else:
        return {"error": f"Failed to deactivate entry {entry_id}"}
