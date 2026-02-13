import os

from google.adk.agents import LlmAgent, ParallelAgent, SequentialAgent
from google.adk.tools.function_tool import FunctionTool
from google.adk.tools.mcp_tool.mcp_toolset import McpToolset, StdioConnectionParams
from mcp import StdioServerParameters

from processing_pipeline.constants import GeminiModel
from processing_pipeline.stage_4.models import ReviewAnalysisOutput
from processing_pipeline.stage_4.tools import (
    deactivate_knowledge_entry,
    search_knowledge_base,
    upsert_knowledge_entry,
)


def build_review_pipeline(prompt_versions: dict[str, dict], reviewer_model: GeminiModel):
    """Build the Stage 4 multi-agent review pipeline.

    Args:
        prompt_versions: Dict with keys 'kb_researcher', 'web_researcher',
            'reviewer', 'kb_updater', each containing a prompt_version dict
            from the database (with 'system_instruction' field).
        reviewer_model: GeminiModel to use for the analysis reviewer agent.

    Returns:
        tuple: (review_pipeline, searxng_toolset)
            - review_pipeline: SequentialAgent for the full review
            - searxng_toolset: McpToolset that must be closed after use
    """
    searxng_toolset = McpToolset(
        connection_params=StdioConnectionParams(
            server_params=StdioServerParameters(
                command="npx",
                args=["-y", "mcp-searxng"],
                env={"SEARXNG_URL": os.environ.get("SEARXNG_URL", "")},
            ),
            timeout=60,
        ),
        tool_filter=["searxng_web_search", "web_url_read"],
    )

    # Agent 1: KB Researcher — searches existing knowledge base
    kb_researcher = LlmAgent(
        name="kb_researcher",
        description="Searches the internal knowledge base for verified facts relevant to the flagged claims.",
        model=GeminiModel.GEMINI_2_5_FLASH_PREVIEW_09_2025,
        instruction=prompt_versions["kb_researcher"]["system_instruction"],
        tools=[FunctionTool(search_knowledge_base)],
        output_key="kb_research",
    )

    # Agent 2: Web Researcher — performs web-based fact-checking
    web_researcher = LlmAgent(
        name="web_researcher",
        description="Performs web-based fact-checking using search engines and source reading.",
        model=GeminiModel.GEMINI_2_5_FLASH_PREVIEW_09_2025,
        instruction=prompt_versions["web_researcher"]["system_instruction"],
        tools=[searxng_toolset],
        output_key="web_research",
    )

    # Agent 3: Analysis Reviewer — produces revised analysis JSON
    analysis_reviewer = LlmAgent(
        name="analysis_reviewer",
        description="Synthesizes research findings to produce a revised disinformation analysis.",
        model=reviewer_model,
        instruction=prompt_versions["reviewer"]["system_instruction"],
        output_key="revised_analysis",
        output_schema=ReviewAnalysisOutput,
    )

    # Agent 4: KB Updater — updates knowledge base with new verified facts
    kb_updater = LlmAgent(
        name="kb_updater",
        description="Updates the knowledge base with newly verified facts from the review.",
        model=GeminiModel.GEMINI_2_5_FLASH_PREVIEW_09_2025,
        instruction=prompt_versions["kb_updater"]["system_instruction"],
        tools=[
            FunctionTool(upsert_knowledge_entry),
            FunctionTool(deactivate_knowledge_entry),
        ],
        output_key="kb_update_summary",
    )

    # Orchestration: parallel research -> sequential review -> KB update
    research_agent = ParallelAgent(
        name="research",
        description="Runs KB and web research in parallel.",
        sub_agents=[kb_researcher, web_researcher],
    )

    review_pipeline = SequentialAgent(
        name="stage4_review_pipeline",
        description="Full Stage 4 review: parallel research, analysis revision, and KB update.",
        sub_agents=[research_agent, analysis_reviewer, kb_updater],
    )

    return review_pipeline, searxng_toolset
