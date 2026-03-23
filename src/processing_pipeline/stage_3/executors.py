import asyncio
from datetime import datetime, timezone
import json

from google import genai
from google.genai.types import (
    AutomaticFunctionCallingConfig,
    File,
    FinishReason,
    GenerateContentConfig,
    ThinkingConfig,
)
from pydantic import ValidationError

from processing_pipeline.constants import GeminiModel
from processing_pipeline.processing_utils import get_safety_settings
from processing_pipeline.stage_3.models import Stage3Output
from processing_pipeline.stage_3.web_tools import searxng_web_search, web_url_read


class Stage3Executor:
    """Executor for Stage 3 in-depth analysis."""

    @classmethod
    async def run_async(
        cls,
        gemini_client: genai.Client,
        model_name: GeminiModel,
        audio_file: str,
        metadata: dict,
        prompt_version: dict,
    ):
        """
        Main execution method for Stage 3 analysis.

        Uses the Google GenAI SDK with web search tools (searxng_web_search,
        web_url_read) for fact checking via automatic function calling.

        Args:
            gemini_client: Google GenAI client instance
            model_name: Name of the Gemini model to use
            audio_file: Path to the audio file
            metadata: Metadata dictionary for the audio clip
            prompt_version: The prompt version to use for analysis

        Returns:
            dict: Structured and validated analysis output
        """

        # Pre-compute temporal context for breaking news protocol
        now = datetime.now(timezone.utc)
        current_date_time = now.strftime("%B %-d, %Y %-I:%M %p UTC")

        recorded_at_str = metadata.get("additional_info", {}).get("recorded_at", "")
        hours_since_recording = ""
        breaking_news_notice = ""
        if recorded_at_str:
            try:
                recorded_at_dt = datetime.strptime(recorded_at_str, "%B %-d, %Y %-I:%M %p")
                recorded_at_dt = recorded_at_dt.replace(tzinfo=timezone.utc)
                delta_hours = round((now - recorded_at_dt).total_seconds() / 3600, 1)
                hours_since_recording = str(delta_hours)
                if delta_hours <= 24:
                    breaking_news_notice = (
                        f"**BREAKING NEWS PROTOCOL APPLIES**: This recording is {delta_hours} hours old (< 24 hours). "
                        f"Maximum confidence score is 20 unless contradictory evidence from tier-1/tier-2 sources is found. "
                        f"Use verification_status: insufficient_evidence."
                    )
                elif delta_hours <= 72:
                    breaking_news_notice = (
                        f"**BREAKING NEWS PROTOCOL APPLIES**: This recording is {delta_hours} hours old (< 72 hours). "
                        f"Maximum confidence score is 30 unless contradictory evidence from tier-1/tier-2 sources is found. "
                        f"Use verification_status: insufficient_evidence."
                    )
            except ValueError:
                pass

        # Prepare the user prompt
        user_prompt = (
            f"{prompt_version['user_prompt']}\n\n"
            f"## Snippet Data\n\n"
            f"- **Current date and time**: {current_date_time}\n"
            f"- **Hours since recording**: {hours_since_recording}\n"
            f"- {breaking_news_notice}\n"
            f"- **Metadata of the attached audio clip**: \n{json.dumps(metadata, indent=2)}\n\n"
            f"**WARNING:** Do NOT treat today's date as a 'future date'. "
            f"Your training data may predate this date — that does NOT make the date wrong.\n\n"
        )

        # Upload audio file
        uploaded_audio_file = gemini_client.files.upload(file=audio_file)

        try:
            while uploaded_audio_file.state.name == "PROCESSING":
                print("Processing the uploaded audio file...")
                await asyncio.sleep(1)
                uploaded_audio_file = gemini_client.files.get(name=uploaded_audio_file.name)

            # Analyze with web search tools
            analysis_text, thought_summaries = await cls.__analyze_with_web_search(
                gemini_client=gemini_client,
                model_name=model_name,
                uploaded_audio_file=uploaded_audio_file,
                user_prompt=user_prompt,
                system_instruction=prompt_version["system_instruction"],
            )

            # Validate with Pydantic, fall back to schema restructuring
            output = cls.__validate_with_pydantic(analysis_text)

            if not output:
                output = await cls.__structure_with_schema(
                    gemini_client, analysis_text, prompt_version["output_schema"]
                )

            return {
                "response": output,
                "grounding_metadata": json.dumps(output.get("verification_evidence"), indent=2),
                "thought_summaries": thought_summaries or output.get("thought_summaries"),
            }
        finally:
            if uploaded_audio_file:
                gemini_client.files.delete(name=uploaded_audio_file.name)

    @classmethod
    async def __analyze_with_web_search(
        cls,
        gemini_client: genai.Client,
        model_name: GeminiModel,
        uploaded_audio_file: File,
        user_prompt: str,
        system_instruction: str,
    ):
        """
        Analyze using the GenAI SDK with web search tools.

        Uses searxng_web_search and web_url_read as plain Python function tools
        with the SDK's automatic function calling.

        Returns:
            tuple: (analysis_text, thought_summaries)
        """
        print("Analyzing with SDK + web search tools...")

        response = await gemini_client.aio.models.generate_content(
            model=model_name,
            contents=[user_prompt, uploaded_audio_file],
            config=GenerateContentConfig(
                system_instruction=system_instruction,
                max_output_tokens=32768,
                tools=[searxng_web_search, web_url_read],
                automatic_function_calling=AutomaticFunctionCallingConfig(
                    maximum_remote_calls=20,
                ),
                thinking_config=ThinkingConfig(thinking_budget=4096, include_thoughts=True),
                safety_settings=get_safety_settings(),
            ),
        )

        thoughts = ""
        if response.candidates and response.candidates[0].content:
            for part in response.candidates[0].content.parts:
                if part.thought and part.text:
                    thoughts += part.text

        if not response.text:
            finish_reason = response.candidates[0].finish_reason if response.candidates else None

            if finish_reason == FinishReason.MAX_TOKENS:
                raise ValueError("The response from Gemini was too long and was cut off.")

            print(f"Response finish reason: {finish_reason}")
            raise ValueError("No response from Gemini.")

        return response.text, thoughts

    @classmethod
    def __validate_with_pydantic(cls, response_text: str):
        try:
            print("Attempting to validate response with Pydantic model...")
            start_idx = response_text.find("{")
            end_idx = response_text.rfind("}")

            if start_idx == -1 or end_idx == -1:
                print("No JSON object found in the response.")
                return None

            parsed = Stage3Output.model_validate_json(response_text[start_idx : end_idx + 1])
            print("Validation successful - returning structured output")
            return parsed.model_dump()
        except ValidationError as e:
            print(f"Validation failed: {e}")
            return None

    @classmethod
    async def __structure_with_schema(
        cls,
        gemini_client: genai.Client,
        analysis_text: str,
        output_schema: dict,
    ):
        print("Restructuring response with schema validation...")

        system_instruction = """You are a helpful assistant whose task is to convert provided text into a valid JSON object following a given schema. Your responsibilities are:

1. **Validation**: Check if the provided text can be converted into a valid JSON object that adheres to the specified schema.
2. **Conversion**:
    - If the text is convertible, convert it into a valid JSON object according to the schema.
    - Set field `"is_convertible": true` in the JSON object.
3. **Error Handling**:
    - If the text is not convertible (e.g., missing fields, incorrect data types), return a JSON object with the field `"is_convertible": false`."""

        user_prompt = f"Please structure the following analysis text into the required JSON format:\n\n{analysis_text}"

        response = await gemini_client.aio.models.generate_content(
            model=GeminiModel.GEMINI_2_5_FLASH,
            contents=[user_prompt],
            config=GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=output_schema,
                system_instruction=system_instruction,
                max_output_tokens=8192,
                thinking_config=ThinkingConfig(thinking_budget=0),
                safety_settings=get_safety_settings(),
            ),
        )

        parsed_response = response.parsed

        if not parsed_response:
            finish_reason = response.candidates[0].finish_reason if response.candidates else None

            if finish_reason == FinishReason.MAX_TOKENS:
                raise ValueError("The response from Gemini was too long and was cut off in step 2.")

            raise ValueError(f"No response from Gemini in step 2. Response finished with reason: {finish_reason}")

        if not parsed_response.get("is_convertible"):
            raise ValueError("[Stage 3] The response from Gemini could not be converted to the required schema.")

        return parsed_response
