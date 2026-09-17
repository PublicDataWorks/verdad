"""Stage 3's first evidence source: semantic search over the dated news ledger (``news_index``).

The ledger is filled only by ``src/news_ledger/`` from wire, public-broadcaster and IFCN fact-checker
feeds, so unlike the knowledge base it cannot be poisoned by the pipeline's own output, and every row
carries a publication date the model can trust over its training cutoff.
"""

import os

from openai import OpenAI

from processing_pipeline.processing_utils import normalize_embedding
from processing_pipeline.supabase_utils import SupabaseClient

EMBEDDING_MODEL = "text-embedding-3-large"
MATCH_COUNT = 5
MATCH_THRESHOLD = 0.5


async def news_ledger_search(
    query: str,
    published_after: str | None = None,
    published_before: str | None = None,
) -> dict:
    """Search a curated index of dated headlines from wire services, public broadcasters and IFCN fact-checkers.

    Call this FIRST for any claim about a named person, event or date, before web search. Every result
    carries a verified publication date, so a match is evidence that an event really happened on that
    date even when it falls after your training cutoff.

    Args:
        query: What to look for, e.g. the claim or the person and event named in the audio.
        published_after: Optional ISO date (YYYY-MM-DD); only return items published on or after it.
        published_before: Optional ISO date (YYYY-MM-DD); only return items published on or before it.

    Returns:
        A dictionary with the query and a list of matching headlines, each with url, title, summary,
        outlet, published_at (YYYY-MM-DD), credibility_tier (1 = wire/public broadcaster/fact-checker)
        and similarity. When the search could not be performed the dictionary has failed=true and an
        error message with an empty results list: treat that as "search failed", not "no results".
    """
    try:
        return await _news_ledger_search(query, published_after, published_before)
    except Exception as e:
        print(f"[news_tools] news_ledger_search failed for {query!r}: {type(e).__name__}: {e}")
        return {"query": query, "failed": True, "error": f"{type(e).__name__}: {e}", "results": []}


async def _news_ledger_search(query: str, published_after: str | None, published_before: str | None) -> dict:
    embedding = _embed_query(query)
    matched = _supabase_client().search_news_index(
        query_embedding=embedding,
        match_threshold=MATCH_THRESHOLD,
        match_count=MATCH_COUNT,
        published_after=published_after,
        published_before=published_before,
    )
    return {
        "query": query,
        "results": [
            {
                "url": item.get("url", ""),
                "title": item.get("title", ""),
                "summary": item.get("summary") or "",
                "outlet": item.get("outlet", ""),
                "published_at": (item.get("published_at") or "")[:10],
                "credibility_tier": item.get("credibility_tier"),
                "similarity": item.get("similarity"),
            }
            for item in matched
        ],
    }


def _embed_query(query: str) -> list[float]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY environment variable is not set")
    response = OpenAI(api_key=api_key).embeddings.create(model=EMBEDDING_MODEL, input=query)
    return normalize_embedding(response.data[0].embedding)


def _supabase_client() -> SupabaseClient:
    return SupabaseClient(supabase_url=os.getenv("SUPABASE_URL"), supabase_key=os.getenv("SUPABASE_KEY"))
