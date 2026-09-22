import asyncio
from unittest.mock import AsyncMock, Mock, patch

from google.adk.tools.mcp_tool.mcp_tool import McpTool
from mcp.types import ListToolsResult, Tool

from processing_pipeline.stage_4.gemini_mcp_toolset import GeminiSafeMcpTool, GeminiSafeMcpToolset, _hide_args

SEARCH_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {"type": "string"},
        "time_range": {"type": "string", "enum": ["day", "month", "year"]},
        "safesearch": {"type": "integer", "enum": [0, 1, 2]},
    },
    "required": ["query", "time_range"],
}


def _search_tool(schema=SEARCH_SCHEMA):
    return Tool(name="searxng_web_search", description="search", inputSchema=schema)


class TestHideArgs:
    def test_drops_the_property_and_its_required_entry(self):
        schema = {"properties": {"query": {}, "time_range": {}}, "required": ["query", "time_range"]}
        _hide_args(schema, frozenset({"time_range"}))
        assert schema == {"properties": {"query": {}}, "required": ["query"]}

    def test_tolerates_a_schema_without_the_arg(self):
        schema = {"properties": {"url": {}}}
        _hide_args(schema, frozenset({"time_range"}))
        assert schema == {"properties": {"url": {}}}


class TestGeminiSafeMcpTool:
    def test_run_async_drops_hidden_args_and_restores_int_enums(self):
        tool = GeminiSafeMcpTool(
            mcp_tool=_search_tool(),
            mcp_session_manager=Mock(),
            int_enum_paths={"safesearch": [0, 1, 2]},
            hidden_args=frozenset({"time_range"}),
        )
        with patch.object(McpTool, "run_async", AsyncMock(return_value={"content": []})) as run:
            asyncio.run(tool.run_async(args={"query": "q", "time_range": "year", "safesearch": "1"}, tool_context=Mock()))
        assert run.call_args.kwargs["args"] == {"query": "q", "safesearch": 1}


class TestGeminiSafeMcpToolset:
    def _toolset(self, **kwargs):
        with patch("processing_pipeline.stage_4.gemini_mcp_toolset.McpToolset.__init__", return_value=None):
            toolset = GeminiSafeMcpToolset(**kwargs)
        for attr in ("_mcp_session_manager", "_auth_scheme", "_auth_credential", "_require_confirmation", "_header_provider"):
            setattr(toolset, attr, None)
        toolset._is_tool_selected = lambda tool, ctx: True
        toolset._execute_with_session = AsyncMock(return_value=ListToolsResult(tools=[_search_tool()]))
        return toolset

    def test_hidden_args_leave_the_schema_the_model_sees(self):
        toolset = self._toolset(hidden_args={"searxng_web_search": {"time_range"}})
        (tool,) = asyncio.run(toolset.get_tools())
        schema = tool._mcp_tool.inputSchema
        assert "time_range" not in schema["properties"] and schema["required"] == ["query"]
        assert schema["properties"]["safesearch"]["enum"] == ["0", "1", "2"]
        assert tool._hidden_args == frozenset({"time_range"})

    def test_no_hidden_args_keeps_the_schema(self):
        (tool,) = asyncio.run(self._toolset().get_tools())
        assert "time_range" in tool._mcp_tool.inputSchema["properties"] and tool._hidden_args == frozenset()
