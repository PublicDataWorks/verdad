"""Stage 3's news ledger tool: its result contract, its failure contract and its registration.

The tool must behave like ``searxng_web_search``: never raise, and signal a failed search with
``failed=true`` and an empty result list rather than an empty "no results" answer.
"""

import asyncio

from processing_pipeline.stage_3 import executors, news_tools
from processing_pipeline.stage_3.news_tools import news_ledger_search
from processing_pipeline.stage_3.web_tools import tool_result_dates, tool_result_urls

MATCH = {
    "id": "1",
    "outlet": "BBC Mundo",
    "url": "https://bbc.example/a",
    "title": "Titular",
    "summary": "Resumen",
    "published_at": "2026-08-07T10:00:00+00:00",
    "credibility_tier": 1,
    "similarity": 0.81,
}


class FakeSupabase:
    def __init__(self, data):
        self.data = data
        self.params = None

    def search_news_index(self, **params):
        self.params = params
        return self.data


def patch_backends(monkeypatch, supabase):
    monkeypatch.setattr(news_tools, "_embed_query", lambda query: [0.1, 0.2])
    monkeypatch.setattr(news_tools, "_supabase_client", lambda: supabase)


def test_successful_search_maps_the_rpc_rows(monkeypatch):
    supabase = FakeSupabase([MATCH])
    patch_backends(monkeypatch, supabase)

    result = asyncio.run(news_ledger_search("Abelardo de la Espriella inauguration", published_after="2026-01-01"))

    assert result["query"] == "Abelardo de la Espriella inauguration"
    assert result["results"] == [
        {
            "url": "https://bbc.example/a",
            "title": "Titular",
            "summary": "Resumen",
            "outlet": "BBC Mundo",
            "published_at": "2026-08-07",
            "credibility_tier": 1,
            "similarity": 0.81,
        }
    ]
    assert supabase.params["published_after"] == "2026-01-01"
    assert supabase.params["published_before"] is None
    assert "failed" not in result


def test_no_matches_is_an_empty_result_not_a_failure(monkeypatch):
    patch_backends(monkeypatch, FakeSupabase([]))

    result = asyncio.run(news_ledger_search("nothing on file"))

    assert result == {"query": "nothing on file", "results": []}


def test_rpc_error_returns_failed_instead_of_raising(monkeypatch):
    class Broken:
        def search_news_index(self, **params):
            raise RuntimeError("PGRST202")

    patch_backends(monkeypatch, Broken())

    result = asyncio.run(news_ledger_search("q"))

    assert result["failed"] is True
    assert result["results"] == []
    assert "PGRST202" in result["error"]


def test_missing_openai_key_returns_failed(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(news_tools, "_supabase_client", lambda: FakeSupabase([]))

    result = asyncio.run(news_ledger_search("q"))

    assert result["failed"] is True
    assert "OPENAI_API_KEY" in result["error"]
    assert result["results"] == []


def test_tool_is_registered_first_in_the_stage_3_tool_set():
    assert list(executors.WEB_TOOLS) == ["news_ledger_search", "searxng_web_search", "web_url_read"]
    assert executors.WEB_TOOLS["news_ledger_search"] is news_ledger_search


def test_docstring_tells_the_model_to_call_it_before_web_search():
    doc = news_ledger_search.__doc__
    assert "fact-checker" in doc
    assert "FIRST" in doc


def test_ledger_urls_count_as_observed_urls(monkeypatch):
    patch_backends(monkeypatch, FakeSupabase([MATCH]))

    result = asyncio.run(news_ledger_search("q"))

    assert tool_result_urls("news_ledger_search", result) == ["https://bbc.example/a"]
    assert tool_result_dates("news_ledger_search", result) == {"https://bbc.example/a": result["results"][0]["published_at"][:10]}
    assert tool_result_urls("news_ledger_search", {"failed": True, "results": [{"url": "https://x"}]}) == []
    assert tool_result_urls("web_url_read", {"url": "https://page.example"}) == ["https://page.example"]
