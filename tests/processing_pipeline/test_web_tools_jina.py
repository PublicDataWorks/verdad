import asyncio
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from processing_pipeline.stage_3 import web_tools

NOW = datetime(2026, 9, 28, 3, 0, tzinfo=timezone.utc)


class _JinaSession:
    calls = []
    payload = {}

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def get(self, url, params=None, headers=None):
        self.calls.append((url, params, headers))
        return self

    def raise_for_status(self):
        pass

    async def json(self):
        return self.payload


def test_jina_search_asks_for_no_content_and_returns_the_searxng_shape(monkeypatch):
    monkeypatch.setenv("JINA_API_KEY", "test-key")
    _JinaSession.calls = []
    _JinaSession.payload = {
        "data": [
            {"title": "UN story", "url": "https://news.un.org/a", "description": "d" * 2000, "date": "Sep 24, 2026"},
            {"title": "No date", "url": "https://example.org/b", "date": None},
        ]
    }
    with patch.object(web_tools.aiohttp, "ClientSession", _JinaSession):
        result = asyncio.run(web_tools.jina_web_search("Zelenskyy UN speech"))

    ((url, params, headers),) = _JinaSession.calls
    assert url == "https://s.jina.ai/"
    assert params == {"q": "Zelenskyy UN speech"}
    assert headers["X-Respond-With"] == "no-content"
    assert headers["Authorization"] == "Bearer test-key"
    first, second = result["results"]
    assert first == {
        "title": "UN story",
        "url": "https://news.un.org/a",
        "content": "d" * web_tools.JINA_CONTENT_CHARS,
        "publishedDate": "2026-09-24",
    }
    assert second["content"] == "" and second["publishedDate"] is None


def test_jina_search_without_key_fails_without_calling_out(monkeypatch):
    monkeypatch.delenv("JINA_API_KEY", raising=False)
    _JinaSession.calls = []
    with patch.object(web_tools.aiohttp, "ClientSession", _JinaSession):
        result = asyncio.run(web_tools.jina_web_search("anything"))
    assert result["failed"] is True and result["results"] == []
    assert _JinaSession.calls == []
    assert not web_tools.jina_search_available()


def test_jina_search_returns_failed_dict_on_exception(monkeypatch):
    class Exploding:
        def __init__(self, *args, **kwargs):
            raise TimeoutError("connect timeout")

    monkeypatch.setenv("JINA_API_KEY", "test-key")
    with patch.object(web_tools.aiohttp, "ClientSession", Exploding):
        result = asyncio.run(web_tools.jina_web_search("anything"))
    assert result["failed"] is True
    assert "TimeoutError" in result["error"]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("4 days ago", "2026-09-24"),
        ("1 week ago", "2026-09-21"),
        ("2 hours ago", "2026-09-28"),
        ("5 Hours ago", "2026-09-27"),
        ("Feb 9, 2018", "2018-02-09"),
        ("September 22, 2026", "2026-09-22"),
        ("2026-09-22T10:00:00Z", "2026-09-22"),
        ("4 months ago", None),
        ("yesterday", None),
        ("", None),
        (None, None),
    ],
)
def test_jina_date(value, expected):
    assert web_tools.jina_date(value, NOW) == expected


def test_jina_results_count_as_observed_search_results():
    result = {"results": [{"url": "https://news.un.org/a", "publishedDate": "2026-09-24"}, {"url": "https://b.org"}]}
    assert web_tools.tool_result_urls("jina_web_search", result) == ["https://news.un.org/a", "https://b.org"]
    assert web_tools.tool_result_dates("jina_web_search", result) == {"https://news.un.org/a": "2026-09-24"}
