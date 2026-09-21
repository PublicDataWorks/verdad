import asyncio
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from processing_pipeline.stage_4.constants import OBSERVED_URLS_STATE_KEY
from processing_pipeline.stage_4.tool_record import (
    READ_TOOL,
    SEARCH_TOOL,
    Stage4ToolRecord,
    ToolRecordPlugin,
    parse_search_result_urls,
)

# mcp-searxng 2.2.0 output: optional metadata section, one block per hit, cache marker
SEARCH_TEXT = """Served by SearXNG instance(s): https://verdad-searxng.fly.dev

---

Title: Marco Rubio confirmed as Secretary of State
Description: The Senate voted 99-0 on Monday.
URL: https://apnews.com/article/rubio-secretary-state-1a2b3c
Relevance Score: 0.912
Published Date: 2026-01-21

Title: Rubio sworn in
Description: Rubio took the oath at the State Department.
URL: https://www.reuters.com/world/us/rubio-sworn-in/?utm_source=rss

_Cached result_"""

NO_RESULTS_TEXT = '🔍 No results found for "x". Try different search terms or check if SearXNG search engines are working.'


def _mcp(text, is_error=False):
    result = {"content": [{"type": "text", "text": text}]}
    if is_error:
        result["isError"] = True
    return result


def _tool(name):
    return SimpleNamespace(name=name)


class TestParseSearchResultUrls:
    def test_reads_every_url_line(self):
        assert parse_search_result_urls(SEARCH_TEXT) == [
            "https://apnews.com/article/rubio-secretary-state-1a2b3c",
            "https://www.reuters.com/world/us/rubio-sworn-in/?utm_source=rss",
        ]

    def test_reads_json_output(self):
        text = json.dumps({"query": "q", "results": [{"title": "t", "url": "https://apnews.com/a"}, {"title": "no url"}]})
        assert parse_search_result_urls(text) == ["https://apnews.com/a"]

    @pytest.mark.parametrize(
        "text",
        [NO_RESULTS_TEXT, "", None, "Title: x\nDescription: see https://apnews.com/a", "{not json", '{"results": "x"}'],
    )
    def test_nothing_without_urls(self, text):
        assert parse_search_result_urls(text) == []


class TestStage4ToolRecord:
    def test_search_results_are_observed_by_url_key(self):
        record = Stage4ToolRecord()
        record.record(SEARCH_TOOL, {"query": "Rubio Secretary of State", "time_range": "month"}, _mcp(SEARCH_TEXT))

        assert record.searches == [
            {
                "query": "Rubio Secretary of State",
                "time_range": "month",
                "status": "results_found",
                "urls": parse_search_result_urls(SEARCH_TEXT),
            }
        ]
        assert record.observed == {"apnews.com/article/rubio-secretary-state-1a2b3c", "reuters.com/world/us/rubio-sworn-in"}

    def test_no_results_and_errors_observe_nothing(self):
        record = Stage4ToolRecord()
        record.record(SEARCH_TOOL, {"query": "a"}, _mcp(NO_RESULTS_TEXT))
        record.record(SEARCH_TOOL, {"query": "b"}, _mcp("🌐 Timeout Error: x", is_error=True), failed=True)
        record.record(SEARCH_TOOL, {"query": "c"}, None, failed=True)

        assert [s["status"] for s in record.searches] == ["no_results", "failed", "failed"]
        assert record.observed == set()

    def test_successful_read_observes_the_fetched_url(self):
        record = Stage4ToolRecord()
        record.record(READ_TOOL, {"url": "https://www.politifact.com/factchecks/2026/x/"}, _mcp("# Article\n\nBody"))

        assert record.fetches == [{"url": "https://www.politifact.com/factchecks/2026/x/", "status": "ok"}]
        assert record.observed == {"politifact.com/factchecks/2026/x"}

    @pytest.mark.parametrize(
        "result, failed",
        [
            (_mcp("📄 Content Warning: Page fetched but appears empty after conversion (https://x.com/a)."), False),
            (_mcp("🌐 DNS Error: x", is_error=True), True),
            (None, True),
        ],
    )
    def test_failed_or_empty_read_observes_nothing(self, result, failed):
        record = Stage4ToolRecord()
        record.record(READ_TOOL, {"url": "https://x.com/a"}, result, failed=failed)

        assert record.fetches == [{"url": "https://x.com/a", "status": "failed"}]
        assert record.observed == set()

    def test_to_dict(self):
        record = Stage4ToolRecord()
        record.record(READ_TOOL, {"url": "https://b.com/2"}, _mcp("x"))
        record.record(READ_TOOL, {"url": "https://a.com/1"}, _mcp("y"))

        assert record.to_dict() == {
            "searches": [],
            "fetches": [{"url": "https://b.com/2", "status": "ok"}, {"url": "https://a.com/1", "status": "ok"}],
            "observed_urls": ["a.com/1", "b.com/2"],
        }


class TestToolRecordPlugin:
    def test_after_tool_records_and_publishes_observed_urls_to_state(self):
        plugin = ToolRecordPlugin()
        context = Mock(state={OBSERVED_URLS_STATE_KEY: []})

        returned = asyncio.run(
            plugin.after_tool_callback(
                tool=_tool(SEARCH_TOOL), tool_args={"query": "q"}, tool_context=context, result=_mcp(SEARCH_TEXT)
            )
        )

        assert returned is None
        assert plugin.record.searches[0]["status"] == "results_found"
        assert context.state[OBSERVED_URLS_STATE_KEY] == [
            "apnews.com/article/rubio-secretary-state-1a2b3c",
            "reuters.com/world/us/rubio-sworn-in",
        ]

    def test_is_error_result_is_a_failed_call(self):
        plugin = ToolRecordPlugin()
        context = Mock(state={})

        asyncio.run(
            plugin.after_tool_callback(
                tool=_tool(READ_TOOL),
                tool_args={"url": "https://x.com/a"},
                tool_context=context,
                result=_mcp("🌐 Timeout Error: x", is_error=True),
            )
        )

        assert plugin.record.fetches == [{"url": "https://x.com/a", "status": "failed"}]
        assert context.state[OBSERVED_URLS_STATE_KEY] == []

    def test_tool_error_is_recorded_and_left_to_the_next_plugin(self):
        plugin = ToolRecordPlugin()
        context = Mock(state={})

        returned = asyncio.run(
            plugin.on_tool_error_callback(
                tool=_tool(SEARCH_TOOL), tool_args={"query": "q"}, tool_context=context, error=RuntimeError("boom")
            )
        )

        assert returned is None
        assert plugin.record.searches == [{"query": "q", "time_range": None, "status": "failed", "urls": []}]

    def test_ignores_knowledge_base_tools(self):
        plugin = ToolRecordPlugin()
        context = Mock(state={})

        asyncio.run(
            plugin.after_tool_callback(
                tool=_tool("upsert_knowledge_entry"), tool_args={}, tool_context=context, result={"status": "success"}
            )
        )

        assert plugin.record.to_dict() == {"searches": [], "fetches": [], "observed_urls": []}
        assert OBSERVED_URLS_STATE_KEY not in context.state
