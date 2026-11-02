import asyncio
import inspect
from unittest.mock import patch

from processing_pipeline.stage_3 import web_tools
from processing_pipeline.stage_3.models import SearchPerformed


class _ExplodingSession:
    def __init__(self, *args, **kwargs):
        raise TimeoutError("connect timeout")


def test_search_never_sends_time_range():
    # VER-400: a time_range gets 0 results while bing is the only engine answering
    calls = []

    class CapturingSession:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def get(self, url, params=None):
            calls.append((url, params))
            return self

        def raise_for_status(self):
            pass

        async def json(self):
            return {"results": []}

    with (
        patch.object(web_tools, "SEARXNG_URL", "http://searx.local"),
        patch.object(web_tools.aiohttp, "ClientSession", CapturingSession),
    ):
        asyncio.run(web_tools.searxng_web_search("anything", pageno=2, language="es", safesearch=1))
    assert "time_range" not in inspect.signature(web_tools.searxng_web_search).parameters
    assert calls == [
        (
            "http://searx.local/search",
            {"q": "anything", "format": "json", "pageno": 2, "language": "es", "safesearch": 1},
        )
    ]


def test_search_returns_failed_dict_on_exception():
    with (
        patch.object(web_tools, "SEARXNG_URL", "http://searx.local"),
        patch.object(web_tools.aiohttp, "ClientSession", _ExplodingSession),
    ):
        result = asyncio.run(web_tools.searxng_web_search("anything"))
    assert result["failed"] is True
    assert result["results"] == []
    assert "TimeoutError" in result["error"]


def test_search_reports_missing_config_as_failure():
    with patch.object(web_tools, "SEARXNG_URL", ""):
        result = asyncio.run(web_tools.searxng_web_search("anything"))
    assert result["failed"] is True and "SEARXNG_URL" in result["error"]


def test_url_read_returns_failed_dict_on_exception():
    with patch.object(web_tools.aiohttp, "ClientSession", _ExplodingSession):
        result = asyncio.run(web_tools.web_url_read("https://example.com/x"))
    assert result == {
        "url": "https://example.com/x",
        "failed": True,
        "error": "TimeoutError: connect timeout",
        "content": "",
    }


def test_search_failed_is_a_valid_result_status():
    search = SearchPerformed(query="q", search_intent="i", result_status="search_failed")
    assert search.result_status == "search_failed"
