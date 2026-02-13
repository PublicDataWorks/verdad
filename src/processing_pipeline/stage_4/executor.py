import json
from typing import Optional

from google.adk.apps.app import App
from google.adk.plugins.base_plugin import BasePlugin
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext
from google.genai import types

from processing_pipeline.constants import GeminiModel
from processing_pipeline.stage_4.agents import build_review_pipeline


class ToolErrorHandlerPlugin(BasePlugin):
    """Catches tool execution errors and returns them as results to the model."""

    def __init__(self):
        super().__init__(name="tool_error_handler")

    async def on_tool_error_callback(
        self,
        *,
        tool: BaseTool,
        tool_args: dict,
        tool_context: ToolContext,
        error: Exception,
    ) -> Optional[dict]:
        print(f"  [plugin] Tool '{tool.name}' failed: {error}")
        return {"error": f"Tool '{tool.name}' failed: {error}"}


class Stage4Executor:

    @classmethod
    async def run_async(
        cls,
        snippet_id: str,
        transcription: str,
        disinformation_snippet: str,
        metadata: dict,
        analysis_json: dict,
        recorded_at: str,
        current_time: str,
        prompt_versions: dict[str, dict],
        reviewer_model: GeminiModel,
    ):
        """Run the agentic review pipeline.

        Args:
            transcription: Full transcription text.
            disinformation_snippet: The flagged snippet text.
            metadata: Dict of audio file metadata.
            analysis_json: Dict of Stage 3 analysis.
            snippet_id: Snippet ID.
            prompt_versions: Dict of prompt versions for each agent.
            recorded_at: ISO 8601 recording timestamp.
            current_time: ISO 8601 current UTC time.
            reviewer_model: GeminiModel enum for the analysis reviewer.

        Returns:
            tuple: (result_dict, grounding_metadata_str)
        """
        if not transcription or not metadata or not analysis_json:
            raise ValueError("All inputs (transcription, metadata, analysis_json) must be provided")

        if not disinformation_snippet:
            print("Warning: Disinformation Snippet was not provided for Review")

        # Build the agent pipeline
        review_pipeline, searxng_toolset = build_review_pipeline(prompt_versions, reviewer_model)
        session_service = InMemorySessionService()
        app_name = "stage4_review"
        user_id = "pipeline"
        session_id = f"stage4_review_session_{snippet_id}"

        try:
            session = await session_service.create_session(
                app_name=app_name,
                user_id=user_id,
                session_id=session_id,
                state={
                    "snippet_id": snippet_id,
                    "transcription": transcription,
                    "disinformation_snippet": disinformation_snippet,
                    "metadata": json.dumps(metadata, indent=2),
                    "analysis_json": json.dumps(analysis_json, indent=2),
                    "recorded_at": recorded_at,
                    "current_time": current_time,
                    "kb_research": "",
                    "web_research": "",
                    "revised_analysis": "",
                    "kb_update_summary": "",
                },
            )

            app = App(
                name=app_name,
                root_agent=review_pipeline,
                plugins=[ToolErrorHandlerPlugin()],
            )
            runner = Runner(
                app=app,
                session_service=session_service,
            )

            start_message = types.Content(
                role="user",
                parts=[types.Part(text="Begin the Stage 4 review process for this snippet.")],
            )

            print("Running agentic review pipeline...")
            events_async = runner.run_async(
                session_id=session_id,
                user_id=user_id,
                new_message=start_message,
            )

            # Consume all events to drive the pipeline to completion
            async for event in events_async:
                author = getattr(event, "author", None)
                if not author:
                    continue
                parts = getattr(event.content, "parts", None) if event.content else None
                text = " ".join(p.text for p in parts if getattr(p, "text", None)) if parts else ""
                print(f"  [{author}] {text[:500]}" if text else f"  [{author}] event received")

            # Extract results from session state
            final_session = await session_service.get_session(
                app_name=app_name,
                user_id=user_id,
                session_id=session_id,
            )

            revised_analysis = final_session.state.get("revised_analysis", "")
            if not revised_analysis:
                raise ValueError("No revised analysis produced by the review pipeline")
            result = revised_analysis if isinstance(revised_analysis, dict) else json.loads(revised_analysis)

            grounding_metadata = cls._build_grounding_metadata(
                final_session.state.get("kb_research", ""),
                final_session.state.get("web_research", ""),
                final_session.state.get("kb_update_summary", ""),
            )

            return result, grounding_metadata

        finally:
            print("Closing SEARXNG MCP connection...")
            await searxng_toolset.close()
            print("Cleanup complete.")

    @staticmethod
    def _build_grounding_metadata(kb_research, web_research, kb_update_summary):
        """Build a grounding metadata dict from research findings."""
        metadata = {}
        if kb_research:
            metadata["kb_research"] = kb_research
        if web_research:
            metadata["web_research"] = web_research
        if kb_update_summary:
            metadata["kb_updates"] = kb_update_summary
        return json.dumps(metadata) if metadata else None
