"""
Base agent class for the Prompt Rewriter system.

All agents inherit from BaseAgent, which provides:
- Logging infrastructure
- LLM calling utilities
- Error handling and retry logic
- Database access
"""

import logging
import time
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Generic, TypeVar
from uuid import UUID

from ..config import PromptRewriterConfig, default_config
from ..models import AgentLogEntry

logger = logging.getLogger(__name__)

InputT = TypeVar("InputT")
OutputT = TypeVar("OutputT")


class BaseAgent(ABC, Generic[InputT, OutputT]):
    """
    Base class for all prompt rewriter agents.

    Subclasses must implement:
        - name: str - The agent's name for logging
        - run(input: InputT) -> OutputT - The main execution method
    """

    name: str = "base_agent"

    def __init__(self, config: PromptRewriterConfig | None = None):
        self.config = config or default_config
        self._supabase_client = None

    @property
    def supabase(self):
        """Lazy-load Supabase client."""
        if self._supabase_client is None:
            from supabase import create_client

            self._supabase_client = create_client(
                self.config.supabase_url,
                self.config.supabase_key,
            )
        return self._supabase_client

    @abstractmethod
    async def run(self, input_data: InputT) -> OutputT:
        """
        Execute the agent's main logic.

        Args:
            input_data: Input data specific to this agent type

        Returns:
            Output data specific to this agent type
        """
        pass

    async def execute(
        self, input_data: InputT, proposal_id: UUID | None = None
    ) -> OutputT:
        """
        Execute the agent with logging and error handling.

        This is the main entry point for running an agent. It wraps
        the run() method with logging, timing, and error handling.

        Args:
            input_data: Input data for the agent
            proposal_id: Optional proposal ID for logging context

        Returns:
            Output from the run() method
        """
        log_entry = AgentLogEntry(
            agent_name=self.name,
            proposal_id=proposal_id or UUID("00000000-0000-0000-0000-000000000000"),
            input_summary=self._summarize_input(input_data),
        )

        start_time = time.time()
        logger.info(f"[{self.name}] Starting execution")

        try:
            result = await self.run(input_data)

            elapsed_ms = int((time.time() - start_time) * 1000)
            log_entry.completed_at = datetime.utcnow()
            log_entry.duration_ms = elapsed_ms
            log_entry.status = "completed"
            log_entry.output_summary = self._summarize_output(result)

            logger.info(f"[{self.name}] Completed in {elapsed_ms}ms")

            if proposal_id and self.config.log_all_llm_calls:
                await self._save_log_entry(log_entry)

            return result

        except Exception as e:
            elapsed_ms = int((time.time() - start_time) * 1000)
            log_entry.completed_at = datetime.utcnow()
            log_entry.duration_ms = elapsed_ms
            log_entry.status = "failed"
            log_entry.error_message = str(e)

            logger.error(f"[{self.name}] Failed after {elapsed_ms}ms: {e}")

            if proposal_id and self.config.log_all_llm_calls:
                await self._save_log_entry(log_entry)

            raise

    def _summarize_input(self, input_data: Any) -> str:
        """Create a brief summary of input for logging."""
        if hasattr(input_data, "model_dump"):
            data = input_data.model_dump()
            return str(data)[:500]
        return str(input_data)[:500]

    def _summarize_output(self, output_data: Any) -> str:
        """Create a brief summary of output for logging."""
        if hasattr(output_data, "model_dump"):
            data = output_data.model_dump()
            return str(data)[:500]
        return str(output_data)[:500]

    async def _save_log_entry(self, log_entry: AgentLogEntry) -> None:
        """Save a log entry to the database."""
        try:
            self.supabase.table("prompt_rewriter_agent_logs").insert(
                {
                    "agent_name": log_entry.agent_name,
                    "proposal_id": str(log_entry.proposal_id),
                    "started_at": log_entry.started_at.isoformat(),
                    "completed_at": (
                        log_entry.completed_at.isoformat()
                        if log_entry.completed_at
                        else None
                    ),
                    "duration_ms": log_entry.duration_ms,
                    "status": log_entry.status,
                    "input_data": {"summary": log_entry.input_summary},
                    "output_data": {"summary": log_entry.output_summary},
                    "error_message": log_entry.error_message,
                    "llm_total_tokens": log_entry.llm_tokens_used,
                }
            ).execute()
        except Exception as e:
            logger.warning(f"[{self.name}] Failed to save log entry: {e}")

    async def call_llm(
        self,
        prompt: str,
        system_instruction: str | None = None,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> str:
        """
        Call an LLM with the given prompt.

        This is a utility method for subclasses to use when they need
        to call an LLM. It handles model selection and basic error handling.

        Args:
            prompt: The user prompt
            system_instruction: Optional system instruction
            model: Model to use (defaults to config.default_llm_model)
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate

        Returns:
            The LLM's response text
        """
        import google.generativeai as genai

        model_name = model or self.config.default_llm_model

        generation_config = genai.GenerationConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
        )

        model_instance = genai.GenerativeModel(
            model_name=model_name,
            system_instruction=system_instruction,
            generation_config=generation_config,
        )

        response = model_instance.generate_content(prompt)
        return response.text

    async def call_llm_with_search(
        self,
        prompt: str,
        system_instruction: str | None = None,
        model: str | None = None,
    ) -> tuple[str, list[dict]]:
        """
        Call an LLM with Google Search grounding enabled.

        Args:
            prompt: The user prompt
            system_instruction: Optional system instruction
            model: Model to use

        Returns:
            Tuple of (response_text, grounding_sources)
        """
        import google.generativeai as genai
        from google.generativeai.types import GenerateContentConfig, Tool
        from google.generativeai.types.content_types import GoogleSearch

        model_name = model or self.config.research_model

        tools = [Tool(google_search=GoogleSearch())]

        config = GenerateContentConfig(
            tools=tools,
            system_instruction=system_instruction,
        )

        model_instance = genai.GenerativeModel(model_name=model_name)

        response = model_instance.generate_content(prompt, generation_config=config)

        # Extract grounding metadata
        sources = []
        if hasattr(response.candidates[0], "grounding_metadata"):
            metadata = response.candidates[0].grounding_metadata
            if hasattr(metadata, "grounding_chunks"):
                for chunk in metadata.grounding_chunks:
                    if hasattr(chunk, "web"):
                        sources.append(
                            {
                                "url": chunk.web.uri,
                                "title": chunk.web.title,
                            }
                        )

        return response.text, sources
