from google import genai
from google.genai.types import (
    GenerateContentConfig,
    HarmBlockThreshold,
    HarmCategory,
    SafetySetting,
    ThinkingConfig,
    Tool,
)
from pydantic import BaseModel

from processing_pipeline.constants import GeminiModel


class GeminiClient:
    def __init__(self, api_key: str):
        self.client = genai.Client(api_key=api_key)

    def generate_content(
        self,
        *,
        model: GeminiModel,
        user_prompt: str,
        system_instruction: str,
        max_output_tokens: int = 8192,
        thinking_budget: int = 1024,
        response_schema: dict | BaseModel | None = None,
        tools: list[Tool] | None = None,
        error_prefix: str | None = None,
    ) -> dict:
        config = GenerateContentConfig(
            system_instruction=system_instruction,
            max_output_tokens=max_output_tokens,
            tools=tools,
            thinking_config=ThinkingConfig(thinking_budget=thinking_budget, include_thoughts=True),
            safety_settings=self._get_safety_settings(),
        )

        if response_schema:
            config.response_mime_type = "application/json"
            config.response_schema = response_schema

        response = self.client.models.generate_content(
            model=model,
            contents=[user_prompt],
            config=config,
        )

        if not response.candidates:
            raise ValueError(f"{error_prefix}: No candidates returned from Gemini.")

        text = response.text
        if not text:
            finish_reason = response.candidates[0].finish_reason
            print(f"Response finish reason: {finish_reason}")
            raise ValueError(f"{error_prefix}: No response from Gemini. Finish reason: {finish_reason}.")

        thought_summaries = ""
        for part in response.candidates[0].content.parts:
            if part.thought and part.text:
                thought_summaries += part.text

        grounding_metadata = None
        if response.candidates[0].grounding_metadata:
            grounding_metadata = response.candidates[0].grounding_metadata.model_dump_json(indent=2)

        return {
            "text": text,
            "parsed": response.parsed,
            "grounding_metadata": grounding_metadata,
            "thought_summaries": thought_summaries,
        }

    def _get_safety_settings(self):
        return [
            SafetySetting(
                category=HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
                threshold=HarmBlockThreshold.BLOCK_NONE,
            ),
            SafetySetting(
                category=HarmCategory.HARM_CATEGORY_HATE_SPEECH,
                threshold=HarmBlockThreshold.BLOCK_NONE,
            ),
            SafetySetting(
                category=HarmCategory.HARM_CATEGORY_HARASSMENT,
                threshold=HarmBlockThreshold.BLOCK_NONE,
            ),
            SafetySetting(
                category=HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
                threshold=HarmBlockThreshold.BLOCK_NONE,
            ),
            SafetySetting(
                category=HarmCategory.HARM_CATEGORY_CIVIC_INTEGRITY,
                threshold=HarmBlockThreshold.BLOCK_NONE,
            ),
        ]
