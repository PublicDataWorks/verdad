"""The news ledger poller: URL normalisation, the age filter, upserts and embedding batching.

Every network boundary (``fetch_feed``, ``embed_texts``) is patched; no test touches the network.
"""

from datetime import datetime, timedelta, timezone

import pytest

from news_ledger import poller
from news_ledger.feeds import Feed

FEED = Feed(name="NPR News", url="https://feeds.npr.org/1001/rss.xml", language="en", tier=1)


def entry(link, title="Headline", summary="Summary", age_hours=1):
    published = datetime.now(timezone.utc) - timedelta(hours=age_hours)
    return {
        "link": link,
        "title": title,
        "summary": summary,
        "published_parsed": published.timetuple(),
    }


class FakeSupabase:
    def __init__(self, pending=None):
        self.upserted = []
        self.pending = pending or []
        self.embeddings = []

    def upsert_news_items(self, items):
        self.upserted.extend(items)
        return items

    def get_news_items_without_embedding(self, limit=500):
        return self.pending

    def upsert_news_index_embedding(self, news_index_id, embedding, model_name):
        self.embeddings.append((news_index_id, embedding, model_name))
        return {"news_index": news_index_id}


class FakeOpenAI:
    """Records the batches it was asked to embed and returns one unit vector per input."""

    def __init__(self):
        self.batches = []
        self.embeddings = self

    def create(self, model, input):
        self.batches.append(list(input))
        return type("R", (), {"data": [type("D", (), {"embedding": [1.0, 0.0, 0.0]})() for _ in input]})()


# --- URL normalisation -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("https://x.example/a?utm_source=rss&id=7", "https://x.example/a?id=7"),
        ("https://x.example/a?utm_medium=feed", "https://x.example/a"),
        ("https://x.example/a#section", "https://x.example/a"),
        ("  https://x.example/a  ", "https://x.example/a"),
        ("https://x.example/a?id=7", "https://x.example/a?id=7"),
        ("", ""),
    ],
)
def test_normalize_url(raw, expected):
    assert poller.normalize_url(raw) == expected


def test_items_that_normalise_to_the_same_url_are_stored_once():
    entries = [entry("https://x.example/a?utm_source=rss"), entry("https://x.example/a#top")]

    items = poller.collect_items(FEED, entries, cutoff=_cutoff(48), max_items=100)

    assert [item["url"] for item in items] == ["https://x.example/a"]


# --- Age filter and row shape ------------------------------------------------------------------


def _cutoff(hours):
    return datetime.now(timezone.utc) - timedelta(hours=hours)


def test_entries_older_than_the_cutoff_are_dropped():
    entries = [entry("https://x.example/new", age_hours=2), entry("https://x.example/old", age_hours=100)]

    items = poller.collect_items(FEED, entries, cutoff=_cutoff(48), max_items=100)

    assert [item["url"] for item in items] == ["https://x.example/new"]


def test_undated_and_untitled_entries_are_dropped():
    undated = {"link": "https://x.example/a", "title": "T", "summary": ""}
    untitled = entry("https://x.example/b", title="  ")

    assert poller.collect_items(FEED, [undated, untitled], cutoff=_cutoff(48), max_items=100) == []


def test_max_items_per_feed_is_honoured():
    entries = [entry(f"https://x.example/{i}") for i in range(10)]

    assert len(poller.collect_items(FEED, entries, cutoff=_cutoff(48), max_items=3)) == 3


def test_row_carries_the_feed_metadata_and_a_content_hash():
    (item,) = poller.collect_items(FEED, [entry("https://x.example/a")], cutoff=_cutoff(48), max_items=10)

    assert item["outlet"] == "NPR News"
    assert item["feed_url"] == FEED.url
    assert item["language"] == "en"
    assert item["credibility_tier"] == 1
    assert item["content_hash"] == poller.content_hash("Headline", "Summary")
    assert item["published_at"].endswith("+00:00")


def test_embedding_document_includes_outlet_and_date():
    document = poller.embedding_document(
        {"title": "T", "summary": "S", "outlet": "NPR News", "published_at": "2026-09-16T12:00:00+00:00"}
    )

    assert document == "Headline: T\n\nSummary: S\n\nOutlet: NPR News (2026-09-16)"


# --- poll_feeds --------------------------------------------------------------------------------


def test_poll_feeds_upserts_items_and_embeds_pending_rows(monkeypatch):
    monkeypatch.setattr(poller, "fetch_feed", lambda url: [entry("https://x.example/a")])
    supabase = FakeSupabase(pending=[{"id": "1", "title": "T", "summary": "S", "outlet": "O", "published_at": "2026-09-16T00:00:00+00:00"}])
    openai_client = FakeOpenAI()

    summary = poller.poll_feeds(supabase, openai_client, [FEED])

    assert summary == {"feeds": 1, "items": 1, "embedded": 1, "errors": []}
    assert supabase.upserted[0]["url"] == "https://x.example/a"
    assert supabase.embeddings[0][0] == "1"
    assert supabase.embeddings[0][2] == poller.EMBEDDING_MODEL


def test_poll_feeds_records_a_failing_feed_and_keeps_going(monkeypatch):
    other = Feed(name="Other", url="https://other.example/rss", language="es", tier=2)

    def fetch(url):
        if url == FEED.url:
            raise RuntimeError("boom")
        return [entry("https://x.example/a")]

    monkeypatch.setattr(poller, "fetch_feed", fetch)
    supabase = FakeSupabase()

    summary = poller.poll_feeds(supabase, FakeOpenAI(), [FEED, other])

    assert summary["feeds"] == 1
    assert summary["items"] == 1
    assert summary["errors"] == ["NPR News: RuntimeError: boom"]


def test_embedding_failure_is_recorded_not_raised(monkeypatch):
    monkeypatch.setattr(poller, "fetch_feed", lambda url: [])

    def broken(client, texts):
        raise RuntimeError("no key")

    monkeypatch.setattr(poller, "embed_texts", broken)
    supabase = FakeSupabase(pending=[{"id": "1", "title": "T", "summary": None, "outlet": "O", "published_at": "2026-09-16T00:00:00+00:00"}])

    summary = poller.poll_feeds(supabase, FakeOpenAI(), [FEED])

    assert summary["embedded"] == 0
    assert summary["errors"] == ["embedding: RuntimeError: no key"]


def test_embed_pending_batches_requests():
    pending = [
        {"id": str(i), "title": f"T{i}", "summary": "S", "outlet": "O", "published_at": "2026-09-16T00:00:00+00:00"}
        for i in range(5)
    ]
    supabase = FakeSupabase(pending=pending)
    openai_client = FakeOpenAI()

    embedded = poller.embed_pending(supabase, openai_client, batch_size=2)

    assert embedded == 5
    assert [len(batch) for batch in openai_client.batches] == [2, 2, 1]
    assert len(supabase.embeddings) == 5


def test_embed_texts_normalises_vectors():
    vectors = poller.embed_texts(FakeOpenAI(), ["a", "b"])

    assert all(abs(sum(v * v for v in vector) - 1.0) < 1e-9 for vector in vectors)
