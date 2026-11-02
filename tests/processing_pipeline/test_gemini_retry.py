import pytest
from google.genai import errors

from processing_pipeline.gemini_retry import is_transient


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
        (ExceptionGroup("agents", [api_error(429)]), True),
        (ExceptionGroup("agents", [api_error(429), KeyError("tool")]), False),
    ],
)
def test_is_transient(exc, expected):
    assert is_transient(exc) is expected
