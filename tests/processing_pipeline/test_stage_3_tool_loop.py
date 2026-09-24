"""Stage 3 executor: the explicit tool-calling loop must survive hallucinated tool names.

With the SDK's automatic function calling, a request for a tool that does not exist
(``search``, ``run``, ``call``...) escaped as a bare ``KeyError`` and failed the analysis.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from google.genai.types import (
    Candidate,
    Content,
    FunctionCall,
    GenerateContentResponse,
    GenerateContentResponseUsageMetadata,
    Part,
)

from processing_pipeline.constants import GeminiModel
from processing_pipeline.stage_3 import executors
from processing_pipeline.stage_3.executors import Stage3Executor

analyze = Stage3Executor._Stage3Executor__analyze_with_web_search


def model_turn(*parts):
    return GenerateContentResponse(candidates=[Candidate(content=Content(role="model", parts=list(parts)))])


def tool_call(name, **args):
    return Part(function_call=FunctionCall(name=name, args=args))


def uploaded_file():
    return SimpleNamespace(uri="https://files.example/abc", mime_type="audio/mpeg", name="files/abc")


def fake_client(*turns):
    client = Mock()
    client.aio.models.generate_content = AsyncMock(side_effect=list(turns))
    return client


def run(client):
    return asyncio.run(
        analyze(
            gemini_client=client,
            model_name=GeminiModel.GEMINI_2_5_PRO,
            uploaded_audio_file=uploaded_file(),
            user_prompt="analyze this",
            system_instruction="be careful",
        )
    )


def function_responses(call):
    """The function-response parts the executor sent back in ``call`` (the SDK call after a tool round)."""
    return [p.function_response for p in call.kwargs["contents"][-1].parts]


def test_unknown_tool_name_is_reported_to_the_model_instead_of_raising():
    client = fake_client(
        model_turn(tool_call("run", cmd="ls")),
        model_turn(Part.from_text(text='{"final": true}')),
    )

    text, thoughts, usage, _ = run(client)

    assert text == '{"final": true}'
    assert client.aio.models.generate_content.await_count == 2
    second = client.aio.models.generate_content.await_args_list[1]
    (response,) = function_responses(second)
    assert response.name == "run"
    assert "Unknown tool 'run'" in response.response["error"]
    assert "searxng_web_search, web_url_read" in response.response["error"]
    # The model's own turn is echoed back before the tool responses, as the API requires.
    assert second.kwargs["contents"][-2].parts[0].function_call.name == "run"


@pytest.mark.parametrize(
    ("name", "args", "target"),
    [
        ("call", {"query": "who said it"}, "searxng_web_search"),
        ("search", {"query": "who said it", "pageno": 2.0}, "searxng_web_search"),
        ("searxxng_web_search", {"query": "who said it"}, "searxng_web_search"),
        ("run", {"url": "https://reuters.com/a"}, "web_url_read"),
    ],
)
def test_unknown_tool_name_with_known_arguments_runs_the_matching_tool(monkeypatch, name, args, target):
    seen = {}

    async def fake_tool(**kwargs) -> dict:
        seen.update(kwargs)
        return {"results": [{"url": "https://apnews.com/a"}]} if "query" in kwargs else {"url": kwargs["url"]}

    monkeypatch.setitem(executors.WEB_TOOLS, target, fake_tool)
    client = fake_client(model_turn(tool_call(name, **args)), model_turn(Part.from_text(text="done")))

    _, _, _, observed = run(client)

    assert seen == {key: int(value) if isinstance(value, float) else value for key, value in args.items()}
    (response,) = function_responses(client.aio.models.generate_content.await_args_list[1])
    assert response.name == name
    assert "result" in response.response
    assert observed.urls == ({"apnews.com/a"} if target == "searxng_web_search" else {"reuters.com/a"})


def test_known_tool_is_invoked_with_integer_coerced_args(monkeypatch):
    seen = {}

    async def fake_search(query: str, pageno: int = 1) -> dict:
        seen.update(query=query, pageno=pageno)
        return {"query": query, "results": []}

    monkeypatch.setitem(executors.WEB_TOOLS, "searxng_web_search", fake_search)
    client = fake_client(
        model_turn(tool_call("searxng_web_search", query="q", pageno=2.0)),
        model_turn(Part.from_text(text="done")),
    )

    text, _, _, _ = run(client)

    assert text == "done"
    assert seen == {"query": "q", "pageno": 2}
    (response,) = function_responses(client.aio.models.generate_content.await_args_list[1])
    assert response.response == {"result": {"query": "q", "results": []}}


def test_tool_exception_becomes_a_function_response_error(monkeypatch):
    async def broken(url: str) -> dict:
        raise RuntimeError("SEARXNG_URL environment variable is not set")

    monkeypatch.setitem(executors.WEB_TOOLS, "web_url_read", broken)
    client = fake_client(
        model_turn(tool_call("web_url_read", url="https://x")),
        model_turn(Part.from_text(text="done")),
    )

    run(client)

    (response,) = function_responses(client.aio.models.generate_content.await_args_list[1])
    assert response.response == {"error": "RuntimeError: SEARXNG_URL environment variable is not set"}


def test_endless_tool_calls_stop_at_the_turn_budget():
    client = fake_client(*[model_turn(tool_call("run", cmd="x"))] * executors.MAX_MODEL_TURNS)

    with pytest.raises(ValueError, match="no final answer"):
        run(client)

    assert client.aio.models.generate_content.await_count == executors.MAX_MODEL_TURNS


def test_usage_is_summed_over_every_turn():
    first = model_turn(tool_call("run", cmd="q"))
    first.usage_metadata = GenerateContentResponseUsageMetadata(prompt_token_count=100, total_token_count=120)
    second = model_turn(Part.from_text(text="done"))
    second.usage_metadata = GenerateContentResponseUsageMetadata(prompt_token_count=150, total_token_count=200)

    _, _, usage, _ = run(fake_client(first, second))

    assert usage["prompt_token_count"] == 250
    assert usage["total_token_count"] == 320
    assert usage["thoughts_token_count"] == 0


def test_automatic_function_calling_is_disabled_and_tools_are_declared():
    client = fake_client(model_turn(Part.from_text(text="done")))

    run(client)

    config = client.aio.models.generate_content.await_args.kwargs["config"]
    assert config.automatic_function_calling.disable is True
    declared = [d.name for tool in config.tools for d in tool.function_declarations]
    assert declared == ["searxng_web_search", "web_url_read"]


def test_urls_returned_by_the_tools_are_collected_for_the_evidence_gate(monkeypatch):
    async def fake_search(query: str, pageno: int = 1) -> dict:
        return {
            "query": query,
            "results": [
                {"url": "https://www.apnews.com/article/x/", "publishedDate": "2026-09-15T10:12:00+00:00"},
                {"url": ""},
            ],
        }

    async def fake_read(url: str) -> dict:
        return {"url": url, "content": "..."}

    async def failed_read(url: str) -> dict:
        return {"url": url, "failed": True, "error": "404", "content": ""}

    monkeypatch.setitem(executors.WEB_TOOLS, "searxng_web_search", fake_search)
    monkeypatch.setitem(executors.WEB_TOOLS, "web_url_read", fake_read)
    client = fake_client(
        model_turn(
            tool_call("searxng_web_search", query="q"),
            tool_call("web_url_read", url="http://Reuters.com/a#top"),
        ),
        model_turn(tool_call("run", cmd="hallucinated tool")),
        model_turn(Part.from_text(text="done")),
    )

    _, _, _, observed = run(client)

    assert observed.urls == {"apnews.com/article/x", "reuters.com/a"}
    assert observed.dates == {"apnews.com/article/x": "2026-09-15"}

    monkeypatch.setitem(executors.WEB_TOOLS, "web_url_read", failed_read)
    client = fake_client(
        model_turn(tool_call("web_url_read", url="https://reuters.com/never-existed")),
        model_turn(Part.from_text(text="done")),
    )

    _, _, _, observed = run(client)

    assert observed.urls == set()
    assert observed.dates == {}
