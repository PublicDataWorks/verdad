import asyncio
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from google.genai import errors

from processing_pipeline.gemini_retry import GEMINI_HTTP_OPTIONS, RETRY_DELAYS, is_transient, with_retries


def api_error(code):
    cls = errors.ServerError if code >= 500 else errors.ClientError
    return cls(code, {"error": {"message": "x", "status": "y"}})


@pytest.mark.parametrize(
    "exc, expected",
    [
        (api_error(429), True),
        (api_error(503), True),
        (api_error(400), False),
        (api_error(401), False),
        (ValueError("No response from Gemini."), True),
        (RuntimeError("boom"), False),
        (httpx.ReadTimeout("stalled"), True),
        (TimeoutError(), True),
        (ExceptionGroup("agents", [api_error(429)]), True),
        (ExceptionGroup("agents", [api_error(429), KeyError("tool")]), False),
    ],
)
def test_is_transient(exc, expected):
    assert is_transient(exc) is expected


@pytest.mark.parametrize("exc", [httpx.ReadTimeout("stalled"), TimeoutError()])
def test_with_retries_retries_timeouts(exc):
    attempt = AsyncMock(side_effect=[exc, "ok"])
    with patch("processing_pipeline.gemini_retry.asyncio.sleep", new=AsyncMock()) as sleep:
        assert asyncio.run(with_retries(attempt)) == "ok"
    assert attempt.await_count == 2
    sleep.assert_awaited_once_with(RETRY_DELAYS[0])


def test_gemini_timeout_is_ten_minutes():
    assert GEMINI_HTTP_OPTIONS.timeout == 600_000
