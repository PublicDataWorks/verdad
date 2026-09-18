"""Fetch the configured RSS/Atom feeds and fill the dated news ledger (``news_index``).

Network access is confined to :func:`fetch_feed` (feedparser) and :func:`embed_texts` (OpenAI), so tests
patch those two and never touch the network.
"""

import hashlib
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import feedparser

from news_ledger.feeds import Feed
from processing_pipeline.processing_utils import normalize_embedding

EMBEDDING_MODEL = "text-embedding-3-large"
EMBEDDING_BATCH_SIZE = 64


def normalize_url(url: str) -> str:
    """Drop tracking parameters and the fragment so the same article is one row.

    ``news_index.url`` is unique, and feeds hand out the same link with different ``utm_*`` tails.
    """
    if not url:
        return ""
    parts = urlsplit(url.strip())
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_")
    ]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def content_hash(title: str, summary: str | None) -> str:
    return hashlib.sha256(f"{title}\n{summary or ''}".encode("utf-8")).hexdigest()


def published_at_of(entry) -> datetime | None:
    """The entry's publication time as an aware UTC datetime, or None when the feed gives none."""
    parsed = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
    if parsed is None and isinstance(entry, dict):
        parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return None
    return datetime(*parsed[:6], tzinfo=timezone.utc)


def _get(entry, key: str, default=""):
    if isinstance(entry, dict):
        return entry.get(key, default) or default
    return getattr(entry, key, default) or default


def embedding_document(item: dict) -> str:
    """The text embedded for one ledger row. The date is part of it on purpose: it is what Stage 3 needs."""
    published = item["published_at"][:10]
    return (
        f"Headline: {item['title']}\n\n"
        f"Summary: {item.get('summary') or ''}\n\n"
        f"Outlet: {item['outlet']} ({published})"
    )


# --- Network boundary ------------------------------------------------------------------------------


def fetch_feed(url: str) -> list:
    """Fetch and parse one feed, returning its entries. The only HTTP call in this module."""
    parsed = feedparser.parse(url)
    return list(parsed.entries or [])


def embed_texts(openai_client, texts: list[str]) -> list[list[float]]:
    """Embed a batch of documents, L2-normalized like every other embedding in the pipeline."""
    response = openai_client.embeddings.create(model=EMBEDDING_MODEL, input=texts)
    return [normalize_embedding(item.embedding) for item in response.data]


# --- Polling ----------------------------------------------------------------------------------------


def collect_items(feed: Feed, entries, cutoff: datetime, max_items: int) -> list[dict]:
    """Turn one feed's entries into ``news_index`` rows, dropping undated and too-old ones."""
    items: list[dict] = []
    seen: set[str] = set()
    for entry in entries:
        if len(items) >= max_items:
            break
        url = normalize_url(_get(entry, "link"))
        if not url or url in seen:
            continue
        title = _get(entry, "title").strip()
        if not title:
            continue
        published = published_at_of(entry)
        if published is None or published < cutoff:
            continue
        summary = _get(entry, "summary").strip() or None
        seen.add(url)
        items.append(
            {
                "outlet": feed.name,
                "feed_url": feed.url,
                "url": url,
                "title": title,
                "summary": summary,
                "published_at": published.isoformat(),
                "language": feed.language,
                "credibility_tier": feed.tier,
                "content_hash": content_hash(title, summary),
            }
        )
    return items


def embed_pending(supabase_client, openai_client, batch_size: int = EMBEDDING_BATCH_SIZE) -> int:
    """Embed every ledger row that has no embedding yet, in batches. Returns how many were embedded."""
    pending = supabase_client.get_news_items_without_embedding()
    embedded = 0
    for start in range(0, len(pending), batch_size):
        batch = pending[start : start + batch_size]
        vectors = embed_texts(openai_client, [embedding_document(item) for item in batch])
        for item, vector in zip(batch, vectors, strict=True):
            supabase_client.upsert_news_index_embedding(
                news_index_id=item["id"], embedding=vector, model_name=EMBEDDING_MODEL
            )
            embedded += 1
    return embedded


def poll_feeds(
    supabase_client,
    openai_client,
    feeds: list[Feed],
    since_hours: int = 48,
    max_items_per_feed: int = 100,
) -> dict:
    """Poll every feed once, upsert what is new, then embed everything still missing an embedding.

    Returns a summary dict: ``{"feeds": n, "items": n, "embedded": n, "errors": [...]}``. A feed that
    fails is recorded and skipped; one bad feed must not stop the rest.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    summary = {"feeds": 0, "items": 0, "embedded": 0, "errors": []}

    for feed in feeds:
        try:
            entries = fetch_feed(feed.url)
            items = collect_items(feed, entries, cutoff, max_items_per_feed)
            if items:
                supabase_client.upsert_news_items(items)
            summary["feeds"] += 1
            summary["items"] += len(items)
            print(f"[news_ledger] {feed.name}: {len(items)} item(s) within {since_hours}h")
        except Exception as e:
            print(f"[news_ledger] {feed.name} failed: {type(e).__name__}: {e}")
            summary["errors"].append(f"{feed.name}: {type(e).__name__}: {e}")

    try:
        summary["embedded"] = embed_pending(supabase_client, openai_client)
    except Exception as e:
        print(f"[news_ledger] embedding failed: {type(e).__name__}: {e}")
        summary["errors"].append(f"embedding: {type(e).__name__}: {e}")

    print(f"[news_ledger] poll complete: {summary}")
    return summary
