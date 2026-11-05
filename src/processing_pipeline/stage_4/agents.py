import os

from google.adk.agents import LlmAgent, ParallelAgent, SequentialAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.models.google_llm import Gemini
from google.adk.models.llm_request import LlmRequest
from google.adk.tools.function_tool import FunctionTool
from google.adk.tools.mcp_tool.mcp_toolset import StdioConnectionParams
from google.genai import types

from processing_pipeline.stage_4.gemini_mcp_toolset import GeminiSafeMcpToolset
from mcp import StdioServerParameters

from processing_pipeline.model_config import (
    ModelFamily,
    ModelName,
    model_family,
    stage4_kb_writer_model,
    stage4_researcher_model,
    thinking_config,
)
from processing_pipeline.stage_4 import constants
from processing_pipeline.stage_4.models import ReviewAnalysisOutput
from processing_pipeline.stage_4.tools import (
    deactivate_knowledge_entry,
    search_knowledge_base,
    upsert_knowledge_entry,
)

# The Gemini key sits on the free tier (gemini-2.5-flash: 15 requests/min) and a research agent fires ~20 tool
# rounds in seconds, so back off per request instead of failing the whole review (outer retries: with_retries)
RETRY_OPTIONS = types.HttpRetryOptions(attempts=6, initial_delay=10, max_delay=60)


def _model(model: ModelName) -> Gemini:
    return Gemini(model=str(model), retry_options=RETRY_OPTIONS)


def reviewer_thinking(model: ModelName) -> types.ThinkingConfig | None:
    """Thinking for ``analysis_reviewer``: ``STAGE4_REVIEWER_THINKING`` (minimal|low|medium|high), else medium on 3.x.

    Gemini 3.x defaults to high thinking and the thoughts count against the 16k output cap, so a long review JSON
    came back truncated and the whole Stage 4 run was retried (Thien, Nov 1 2026). 2.5 keeps its dynamic default
    unless the variable is set; Gemma takes no thinking config at all.
    """
    level = os.getenv("STAGE4_REVIEWER_THINKING") or None
    if level is None and model_family(model) == ModelFamily.LEVEL:
        level = "medium"
    return thinking_config(model, level=level)


def force_first_search(callback_context: CallbackContext, llm_request: LlmRequest) -> None:
    """Make the first model turn a search call; Flash otherwise narrates a search report from memory (VER-406)."""
    if any(part.function_response for content in llm_request.contents for part in content.parts or []):
        return
    llm_request.config.tool_config = types.ToolConfig(
        function_calling_config=types.FunctionCallingConfig(
            mode=types.FunctionCallingConfigMode.ANY, allowed_function_names=["searxng_web_search"]
        )
    )


def build_review_pipeline(prompt_versions: dict[str, dict], reviewer_model: ModelName):
    """Build the Stage 4 multi-agent review pipeline.

    Args:
        prompt_versions: Dict with keys 'kb_researcher', 'web_researcher',
            'reviewer', 'kb_updater', each containing a prompt_version dict
            from the database (with 'system_instruction' field).
        reviewer_model: Model id for the analysis reviewer agent (STAGE4_REVIEWER_MODEL).

    Returns:
        tuple: (review_pipeline, searxng_toolset)
            - review_pipeline: SequentialAgent for the full review
            - searxng_toolset: McpToolset that must be closed after use
    """
    searxng_toolset = GeminiSafeMcpToolset(
        connection_params=StdioConnectionParams(
            server_params=StdioServerParameters(
                command="npx",
                args=["-y", "mcp-searxng@2.2.0"],  # pinned: an unpinned npx pulls whatever is latest at boot
                env={"SEARXNG_URL": os.environ.get("SEARXNG_URL", "")},
            ),
            timeout=60,
        ),
        tool_filter=["searxng_web_search", "web_url_read"],
        # VER-392: time-range queries return nothing while only bing answers, and the model sent one every time
        hidden_args={"searxng_web_search": {"time_range"}},
    )

    # Research agents and KB updater default to Flash: Pro invented citations several times more often (VER-391,
    # PR #122). STAGE4_RESEARCHER_MODEL / STAGE4_KB_WRITER_MODEL override them (model_config.py).
    researcher_model = stage4_researcher_model()
    # Agent 1: KB Researcher — searches existing knowledge base
    kb_researcher = LlmAgent(
        name="kb_researcher",
        description="Searches the internal knowledge base for verified facts relevant to the flagged claims.",
        model=_model(researcher_model),
        instruction=prompt_versions["kb_researcher"]["system_instruction"],
        tools=[FunctionTool(search_knowledge_base)],
        output_key="kb_research",
    )

    # Agent 2: Web Researcher — performs web-based fact-checking
    web_researcher = LlmAgent(
        name="web_researcher",
        description="Performs web-based fact-checking using search engines and source reading.",
        model=_model(researcher_model),
        instruction=prompt_versions["web_researcher"]["system_instruction"],
        tools=[searxng_toolset],
        output_key="web_research",
        before_model_callback=force_first_search,
    )

    # Agent 3: Analysis Reviewer — produces revised analysis JSON
    analysis_reviewer = LlmAgent(
        name="analysis_reviewer",
        description="Synthesizes research findings to produce a revised disinformation analysis.",
        model=_model(reviewer_model),
        instruction=prompt_versions["reviewer"]["system_instruction"],
        output_key="revised_analysis",
        output_schema=ReviewAnalysisOutput,
        generate_content_config=types.GenerateContentConfig(
            max_output_tokens=16384,
            thinking_config=reviewer_thinking(reviewer_model),
        ),
    )

    # Agent 4: KB Updater — updates knowledge base with new verified facts
    kb_updater = LlmAgent(
        name="kb_updater",
        description="Updates the knowledge base with newly verified facts from the review.",
        model=_model(stage4_kb_writer_model()),
        instruction=prompt_versions["kb_updater"]["system_instruction"],
        tools=[
            FunctionTool(upsert_knowledge_entry),
            FunctionTool(deactivate_knowledge_entry),
        ],
        output_key="kb_update_summary",
    )

    # Orchestration: parallel research -> sequential review -> KB update (when enabled)
    research_agent = ParallelAgent(
        name="research",
        description="Runs KB and web research in parallel.",
        sub_agents=[kb_researcher, web_researcher],
    )

    review_pipeline = SequentialAgent(
        name="stage4_review_pipeline",
        description="Full Stage 4 review: parallel research, analysis revision, and KB update when enabled.",
        sub_agents=[research_agent, analysis_reviewer, *([kb_updater] if constants.KB_UPDATER_ENABLED else [])],
    )

    return review_pipeline, searxng_toolset
