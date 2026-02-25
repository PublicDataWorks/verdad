"""Compatibility layer for MCP tools with Gemini's enum restrictions.

Gemini requires all enum values to be strings. MCP servers may expose tools
with integer enums (e.g., [0, 1, 2]), which Gemini rejects with a 400 error.

This module provides McpToolset/McpTool subclasses that:
- Convert integer enum values to strings in tool schemas before Gemini sees them
- Convert string enum values back to integers when calling the MCP server
"""

import copy
from typing import Any, List, Optional

from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.mcp_tool.mcp_tool import McpTool
from google.adk.tools.mcp_tool.mcp_toolset import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import retry_on_errors
from google.adk.tools.tool_context import ToolContext
from mcp.types import ListToolsResult


def _coerce_int_enums_to_str(
    schema: dict[str, Any], path: str = ""
) -> dict[str, list]:
    """Walk a JSON schema in-place, converting integer enum values to strings.

    Returns a mapping of dotted property paths to original enum values,
    used later to reverse the conversion when calling the MCP tool.
    """
    int_enum_paths: dict[str, list] = {}

    if not isinstance(schema, dict):
        return int_enum_paths

    if "enum" in schema and isinstance(schema["enum"], list):
        if any(isinstance(v, (int, float)) and not isinstance(v, bool) for v in schema["enum"]):
            int_enum_paths[path] = schema["enum"]
            schema["enum"] = [str(v) for v in schema["enum"]]
            # Gemini only allows enum on STRING type properties
            schema["type"] = "string"

    if "properties" in schema and isinstance(schema["properties"], dict):
        for prop_name, prop_schema in schema["properties"].items():
            child_path = f"{path}.{prop_name}" if path else prop_name
            int_enum_paths.update(_coerce_int_enums_to_str(prop_schema, child_path))

    if "items" in schema and isinstance(schema["items"], dict):
        int_enum_paths.update(_coerce_int_enums_to_str(schema["items"], path))

    for key in ("anyOf", "oneOf", "allOf"):
        if key in schema and isinstance(schema[key], list):
            for sub_schema in schema[key]:
                if isinstance(sub_schema, dict):
                    int_enum_paths.update(_coerce_int_enums_to_str(sub_schema, path))

    if "$defs" in schema and isinstance(schema["$defs"], dict):
        for def_schema in schema["$defs"].values():
            if isinstance(def_schema, dict):
                int_enum_paths.update(_coerce_int_enums_to_str(def_schema, path))

    return int_enum_paths


def _coerce_str_args_to_int(
    args: dict[str, Any], int_enum_paths: dict[str, list]
) -> dict[str, Any]:
    """Convert string argument values back to integers where the original schema had int enums."""
    if not int_enum_paths:
        return args

    converted = dict(args)
    for path, original_values in int_enum_paths.items():
        str_to_orig = {str(v): v for v in original_values if isinstance(v, (int, float)) and not isinstance(v, bool)}
        parts = path.split(".")
        key = parts[-1] if parts else ""
        if key in converted and isinstance(converted[key], str) and converted[key] in str_to_orig:
            converted[key] = str_to_orig[converted[key]]

    return converted


class GeminiSafeMcpTool(McpTool):
    """McpTool that converts string enum args back to integers for the MCP server."""

    def __init__(self, *, int_enum_paths: dict[str, list], **kwargs):
        super().__init__(**kwargs)
        self._int_enum_paths = int_enum_paths

    async def run_async(self, *, args: dict[str, Any], tool_context: ToolContext) -> Any:
        converted_args = _coerce_str_args_to_int(args, self._int_enum_paths)
        return await super().run_async(args=converted_args, tool_context=tool_context)


class GeminiSafeMcpToolset(McpToolset):
    """McpToolset that sanitizes integer enum values for Gemini compatibility."""

    @retry_on_errors
    async def get_tools(
        self,
        readonly_context: Optional[ReadonlyContext] = None,
    ) -> List[BaseTool]:
        tools_response: ListToolsResult = await self._execute_with_session(
            lambda session: session.list_tools(),
            "Failed to get tools from MCP server",
            readonly_context,
        )

        tools = []
        for tool in tools_response.tools:
            schema = copy.deepcopy(tool.inputSchema)
            int_enum_paths = _coerce_int_enums_to_str(schema)
            tool.inputSchema = schema

            mcp_tool = GeminiSafeMcpTool(
                mcp_tool=tool,
                mcp_session_manager=self._mcp_session_manager,
                auth_scheme=self._auth_scheme,
                auth_credential=self._auth_credential,
                require_confirmation=self._require_confirmation,
                header_provider=self._header_provider,
                int_enum_paths=int_enum_paths,
            )

            if self._is_tool_selected(mcp_tool, readonly_context):
                tools.append(mcp_tool)
        return tools
