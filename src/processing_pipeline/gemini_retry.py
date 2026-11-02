import asyncio
from collections.abc import Awaitable, Callable
from http import HTTPStatus

from google.genai import errors

# Waits between attempts; a 429 burst clears in seconds, a 503 spike in minutes.
RETRY_DELAYS = (30, 120, 300)

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
