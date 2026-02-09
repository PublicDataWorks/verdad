from datetime import datetime, timezone
import json
import os
import subprocess
import tempfile
import time
from typing import Any

from google import genai
from google.genai.types import (
    File,
    FinishReason,
    GenerateContentConfig,
    GoogleSearch,
    ThinkingConfig,
    Tool,
)
from pydantic import ValidationError

from processing_pipeline.constants import (
    GeminiCLIEventType,
    GeminiModel,
)
from processing_pipeline.processing_utils import get_safety_settings
from processing_pipeline.stage_3.models import Stage3Output
from utils import optional_task


class Stage3Executor:
    """Executor for Stage 3 in-depth analysis."""

    @classmethod
    def run(
        cls,
        gemini_key: str,
        model_name: GeminiModel,
        audio_file: str,
        metadata: dict,
        prompt_version: dict,
    ):
        """
        Main execution method for Stage 3 analysis.

        Processing strategy:
        1. Step 1: Try Gemini CLI with custom search, fallback to Google Genai SDK with Google Search grounding if CLI fails
        2. Validate: Try to validate response with Pydantic model
        3. Step 2 (conditional): If validation fails, restructure with response_schema

        Args:
            gemini_key: Google Gemini API key
            model_name: Name of the Gemini model to use
            audio_file: Path to the audio file
            metadata: Metadata dictionary for the audio clip
            prompt_version: The prompt version to use for analysis

        Returns:
            dict: Structured and validated analysis output
        """
        if not gemini_key:
            raise ValueError("Google Gemini API key was not set!")

        client = genai.Client(api_key=gemini_key)

        # Prepare the user prompt using the prompt version
        user_prompt = (
            f"{prompt_version['user_prompt']}\n\n"
            f"Here is the metadata of the attached audio clip:\n{json.dumps(metadata, indent=2)}\n\n"
            f"Here is the current date and time: {datetime.now(timezone.utc).strftime('%B %-d, %Y %-I:%M %p UTC')}\n\n"
        )

        # Strategy: Try CLI first, fallback to SDK
        analysis_text = None
        thought_summaries_from_api = None
        uploaded_audio_file = None

        try:
            user_prompt_with_file = user_prompt + f"Here is the audio file attached: @{os.path.basename(audio_file)}"
            analysis_text = cls.__analyze_with_custom_search(
                model_name=model_name,
                user_prompt=user_prompt_with_file,
                system_instruction=prompt_version["system_instruction"],
            )
        except RuntimeError as e:
            print("Falling back to Google Search grounding with SDK...")

            uploaded_audio_file = client.files.upload(file=audio_file)
            while uploaded_audio_file.state.name == "PROCESSING":
                print("Processing the uploaded audio file...")
                time.sleep(1)
                uploaded_audio_file = client.files.get(name=uploaded_audio_file.name)

            sdk_result = cls.__analyze_with_google_search_grounding(
                client,
                model_name,
                user_prompt,
                uploaded_audio_file,
                system_instruction=prompt_version["system_instruction"],
            )
            analysis_text = sdk_result["text"]
            thought_summaries_from_api = sdk_result.get("thought_summaries")

        try:
            # Try to validate with Pydantic model first
            validated_output = cls.__validate_with_pydantic(analysis_text)

            if validated_output:
                thought_summaries = thought_summaries_from_api or validated_output.get("thought_summaries")
                grounding_metadata = json.dumps(validated_output.get("verification_evidence"), indent=2)
                return {
                    "response": validated_output,
                    "grounding_metadata": grounding_metadata,
                    "thought_summaries": thought_summaries,
                }

            # Step 2: Structure with response_schema (if validation failed)
            structured_output = cls.__structure_with_schema(client, analysis_text, prompt_version["output_schema"])
            thought_summaries = thought_summaries_from_api or structured_output.get("thought_summaries")
            grounding_metadata = json.dumps(structured_output.get("verification_evidence"), indent=2)
            return {
                "response": structured_output,
                "grounding_metadata": grounding_metadata,
                "thought_summaries": thought_summaries,
            }
        finally:
            if uploaded_audio_file:
                client.files.delete(name=uploaded_audio_file.name)

    @optional_task(log_prints=True, retries=3)
    @classmethod
    def __analyze_with_custom_search(
        cls,
        model_name: GeminiModel,
        user_prompt: str,
        system_instruction: str,
    ):
        """
        Analyze using Gemini CLI with custom search tools (MCP-based).

        This method uses the Gemini CLI which provides:
        - Custom search via MCP tools
        - Streaming JSON output
        - System instruction from file

        Returns:
            str: Final response text from Gemini CLI

        Raises:
            RuntimeError: If CLI execution fails (for fallback to SDK method)
        """
        print("Analyzing with Gemini CLI (custom search)...")

        events: list[dict[str, Any]] = []
        final_response = ""
        timeout = 300

        # Write system instruction to a temporary file for CLI
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as tmp_file:
            tmp_file.write(system_instruction)
            system_instruction_path = tmp_file.name

        env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", ""),
            "GEMINI_API_KEY": os.environ["GOOGLE_GEMINI_KEY"],
            "GEMINI_SYSTEM_MD": system_instruction_path,
            "SEARXNG_URL": os.environ.get("SEARXNG_URL", ""),
        }

        cmd = [
            "gemini",
            "--model",
            model_name,
            "--output-format",
            "stream-json",
            user_prompt,
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                env=env,
                timeout=timeout,
            )

            # Parse JSONL output
            for line in result.stdout.strip().split("\n"):
                if not line:
                    continue
                try:
                    event = json.loads(line)
                    events.append(event)

                    # Concatenate assistant message content
                    if event.get("type") == GeminiCLIEventType.MESSAGE and event.get("role") == "assistant":
                        content = event.get("content")
                        if content and isinstance(content, str):
                            final_response += content
                except json.JSONDecodeError:
                    pass

            if result.returncode != 0:
                raise RuntimeError(f"Gemini CLI exited with code {result.returncode}: {result.stderr}")

            if not final_response:
                raise RuntimeError("Gemini CLI returned no response")

            return final_response

        except subprocess.TimeoutExpired as e:
            raise RuntimeError(f"Gemini CLI timed out after {timeout} seconds") from e
        finally:
            if os.path.exists(system_instruction_path):
                os.remove(system_instruction_path)

    @optional_task(log_prints=True, retries=3)
    @classmethod
    def __analyze_with_google_search_grounding(
        cls,
        client: genai.Client,
        model_name: GeminiModel,
        user_prompt: str,
        uploaded_audio_file: File,
        system_instruction: str,
    ):
        print("Analyzing audio with web search...")

        response = client.models.generate_content(
            model=model_name,
            contents=[user_prompt, uploaded_audio_file],
            config=GenerateContentConfig(
                system_instruction=system_instruction,
                max_output_tokens=16384,
                tools=[Tool(google_search=GoogleSearch())],
                thinking_config=ThinkingConfig(thinking_budget=4096, include_thoughts=True),
                safety_settings=get_safety_settings(),
            ),
        )

        thoughts = ""
        for part in response.candidates[0].content.parts:
            if part.thought and part.text:
                thoughts += part.text

        if not response.text:
            finish_reason = response.candidates[0].finish_reason if response.candidates else None

            if finish_reason == FinishReason.MAX_TOKENS:
                raise ValueError("The response from Gemini was too long and was cut off in step 1.")

            print(f"Response finish reason: {finish_reason}")
            raise ValueError("No response from Gemini in step 1.")

        return {
            "text": response.text,
            "thought_summaries": thoughts,
        }

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
    def __structure_with_schema(
        cls,
        client: genai.Client,
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

        response = client.models.generate_content(
            model=GeminiModel.GEMINI_FLASH_LATEST,
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
