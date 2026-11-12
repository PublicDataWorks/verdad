import asyncio
from unittest.mock import patch

import aiohttp
import pytest

from processing_pipeline.stage_3 import web_tools


def parallel_session(payload, calls, error=None):
    """An aiohttp.ClientSession stand-in that records each POST and answers with ``payload``."""

    class Session:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def post(self, url, json=None, headers=None):
            calls.append((url, json, headers))
            return self

        def raise_for_status(self):
            if error:
                raise error

        async def json(self):
            return payload

    return Session


def test_parallel_sources_sends_the_tested_request_and_returns_the_citations(monkeypatch):
    monkeypatch.setenv("PARALLEL_API_KEY", "test-key")
    calls = []
    payload = {
        "mode": "fast",
        "answers": {"accurate": {"type": "noul", "noul": 0.15}},
        "usage": {"input_tokens": 2904, "output_tokens": 0},
        "citations": [
            {"url": "https://apnews.com/article/x", "title": "AP story", "excerpts": ["first", "second"]},
            {"url": "https://example.org/bare"},
            {"title": "no url", "excerpts": ["dropped"]},
        ],
        "decision_id": "decisions_1",
    }
    with patch.object(web_tools.aiohttp, "ClientSession", parallel_session(payload, calls)):
        sources = asyncio.run(web_tools.parallel_sources("The speaker says the island was a blackmail operation."))

    ((url, body, headers),) = calls
    assert url == "https://api.parallel.ai/v1/decisions"
    assert headers == {"x-api-key": "test-key"}
    assert body == {
        "state": "The speaker says the island was a blackmail operation.",
        "questions": {
            "accurate": {
                "type": "noul",
                "instructions": "The speaker's statements about people, events and numbers in this text are accurate.",
                "criteria": {"true": "They are accurate.", "false": "At least one of them is not accurate."},
            }
        },
        "mode": "fast",
    }
    assert sources == [
        {"title": "AP story", "url": "https://apnews.com/article/x", "excerpts": ["first", "second"]},
        {"title": "", "url": "https://example.org/bare", "excerpts": []},
    ]


def test_parallel_sources_without_key_raises_without_calling_out(monkeypatch):
    monkeypatch.delenv("PARALLEL_API_KEY", raising=False)
    calls = []
    with patch.object(web_tools.aiohttp, "ClientSession", parallel_session({}, calls)):
        with pytest.raises(KeyError):
            asyncio.run(web_tools.parallel_sources("anything"))
    assert calls == []


def test_parallel_sources_raises_on_an_http_error(monkeypatch):
    monkeypatch.setenv("PARALLEL_API_KEY", "test-key")
    payment_required = aiohttp.ClientResponseError(request_info=None, history=(), status=402)
    session = parallel_session({"error": "payment required"}, [], error=payment_required)
    with patch.object(web_tools.aiohttp, "ClientSession", session):
        with pytest.raises(aiohttp.ClientResponseError):
            asyncio.run(web_tools.parallel_sources("anything"))
