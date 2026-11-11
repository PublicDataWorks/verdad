import asyncio
from collections.abc import Awaitable, Callable
from http import HTTPStatus

import httpx
from google.genai import errors, types

# Waits between attempts; a 429 burst clears in seconds, a 503 spike in minutes.
RETRY_DELAYS = (30, 120, 300)

# In ms. Without it a dropped connection hangs forever; the longest normal call seen was 316 s (VER-456).
GEMINI_HTTP_OPTIONS = types.HttpOptions(timeout=600_000)
# Flex targets 1-15 min per call; cutting one at 10 min would pay it again on standard.
FLEX_HTTP_OPTIONS = types.HttpOptions(timeout=960_000)

TRANSIENT_HTTP = {
    HTTPStatus.REQUEST_TIMEOUT,
    HTTPStatus.TOO_MANY_REQUESTS,
    HTTPStatus.INTERNAL_SERVER_ERROR,
    HTTPStatus.BAD_GATEWAY,
    HTTPStatus.SERVICE_UNAVAILABLE,
    HTTPStatus.GATEWAY_TIMEOUT,
}


def is_transient(e: Exception) -> bool:
    # The ADK agent pipeline (Stage 4) raises its errors inside an ExceptionGroup.
    if isinstance(e, ExceptionGroup):
        return all(is_transient(inner) for inner in e.exceptions)
    if isinstance(e, errors.APIError):
        return e.code in TRANSIENT_HTTP
    # GEMINI_HTTP_OPTIONS timeout: httpx raises on sync calls, aiohttp a plain TimeoutError on async ones.
    if isinstance(e, (httpx.TimeoutException, TimeoutError)):
        return True
    # Empty, truncated or unparseable model output; see Stage3Executor.
    return isinstance(e, ValueError)


async def with_retries(attempt: Callable[[], Awaitable]):
    for delay in RETRY_DELAYS:
        try:
            return await attempt()
        except Exception as e:
            if not is_transient(e):
                raise
            print(f"{type(e).__name__}: {e} Retrying in {delay} s")
            await asyncio.sleep(delay)
    return await attempt()
