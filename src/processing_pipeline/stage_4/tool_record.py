import json
import re
from typing import Optional

from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.plugins.base_plugin import BasePlugin
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext
from google.genai import types

from processing_pipeline.kb_sources import url_key
from processing_pipeline.stage_4.constants import OBSERVED_URLS_STATE_KEY

SEARCH_TOOL = "searxng_web_search"
READ_TOOL = "web_url_read"
KB_SEARCH_TOOL = "search_knowledge_base"

# mcp-searxng renders each hit as "Title: ...\nDescription: ...\nURL: ..." blocks, or as {"results": [{"url": ...}]}
# when the model asks for response_format=json
_RESULT_URL_RE = re.compile(r"^URL: (\S+)$", re.MULTILINE)
# mcp-searxng answers an empty page with a "Content Warning" text, not an error
_EMPTY_PAGE_RE = re.compile(r"^\W*Content Warning:")


def parse_search_result_urls(text) -> list[str]:
    text = text or ""
    if text.lstrip().startswith("{"):
        try:
            results = json.loads(text).get("results") or []
        except (ValueError, AttributeError):
            return []
        return [r["url"] for r in results if isinstance(r, dict) and isinstance(r.get("url"), str) and r["url"]]
    return _RESULT_URL_RE.findall(text)


def _mcp_failed(result) -> bool:
    # a real MCP result always carries a content list; the error handler's {"error": ...} does not
    return not isinstance(result, dict) or bool(result.get("isError")) or not isinstance(result.get("content"), list)


def _result_text(result) -> str:
    return "\n".join(p.get("text") or "" for p in result["content"] if isinstance(p, dict))


class Stage4ToolRecord:
    """What the search, read and KB tools returned during one review (Stage 4's ``ObservedToolOutput``).

    ``observed`` holds the ``url_key`` of every URL a successful call put in front of the model: search hits,
    fetched pages and the sources of curated KB entries (pipeline-written entries are context only, so their
    sources never become citable through this record). A failed call contributes nothing.
    """

    def __init__(self):
        self.searches: list[dict] = []
        self.fetches: list[dict] = []
        self.kb_searches: list[dict] = []
        self.observed: set[str] = set()

    def record(self, tool_name: str, tool_args: dict, result, failed: bool = False) -> None:
        if tool_name == KB_SEARCH_TOOL:
            self._record_kb_search(tool_args, result, failed)
            return
        failed = failed or _mcp_failed(result)
        if tool_name == SEARCH_TOOL:
            urls = [] if failed else parse_search_result_urls(_result_text(result))
            status = "failed" if failed else ("results_found" if urls else "no_results")
            self.searches.append(
                {"query": tool_args.get("query"), "time_range": tool_args.get("time_range"), "status": status, "urls": urls}
            )
            self.observed.update(filter(None, map(url_key, urls)))
        elif tool_name == READ_TOOL:
            url = tool_args.get("url")
            failed = failed or bool(_EMPTY_PAGE_RE.match(_result_text(result)))
            self.fetches.append({"url": url, "status": "failed" if failed else "ok"})
            if not failed and url_key(url):
                self.observed.add(url_key(url))

    def _record_kb_search(self, tool_args: dict, result, failed: bool) -> None:
        entries = result.get("results") if not failed and isinstance(result, dict) else None
        entries = [e for e in entries if isinstance(e, dict)] if isinstance(entries, list) else []
        urls = [
            source["url"]
            for entry in entries
            if entry.get("provenance") == "curated"
            for source in entry.get("sources") or []
            if isinstance(source, dict) and source.get("url")
        ]
        self.kb_searches.append(
            {
                "query": tool_args.get("query"),
                "status": "failed" if failed else "ok",
                "entries": len(entries),
                "curated_source_urls": urls,
            }
        )
        self.observed.update(filter(None, map(url_key, urls)))

    def to_dict(self) -> dict:
        return {
            "searches": self.searches,
            "fetches": self.fetches,
            "kb_searches": self.kb_searches,
            "observed_urls": sorted(self.observed),
        }


class ToolRecordPlugin(BasePlugin):
    """Records every search, read and KB-search call and publishes the observed URLs to session state."""

    def __init__(self):
        super().__init__(name="tool_record")
        self.record = Stage4ToolRecord()
        self._errored: set[str] = set()

    async def before_agent_callback(self, *, agent: BaseAgent, callback_context: CallbackContext) -> Optional[types.Content]:
        # parallel tool calls merge their state deltas in call order, so a stale snapshot can win; republish
        self._publish(callback_context)
        return None

    async def after_tool_callback(
        self, *, tool: BaseTool, tool_args: dict, tool_context: ToolContext, result: dict
    ) -> Optional[dict]:
        if tool_context.function_call_id in self._errored:
            return None  # already recorded as failed; this result is the error handler's substitute
        self._record(tool.name, tool_args, tool_context, result, failed=False)
        return None

    async def on_tool_error_callback(
        self, *, tool: BaseTool, tool_args: dict, tool_context: ToolContext, error: Exception
    ) -> Optional[dict]:
        self._errored.add(tool_context.function_call_id)
        self._record(tool.name, tool_args, tool_context, None, failed=True)
        return None  # the next plugin turns the error into a tool response

    def _record(self, tool_name, tool_args, tool_context, result, failed) -> None:
        if tool_name not in (SEARCH_TOOL, READ_TOOL, KB_SEARCH_TOOL):
            return
        self.record.record(tool_name, tool_args or {}, result, failed)
        self._publish(tool_context)

    def _publish(self, context) -> None:
        # whole-value assignment: in-place mutation of a state value records no delta
        context.state[OBSERVED_URLS_STATE_KEY] = sorted(self.record.observed)
