from datetime import datetime, timezone
from http import HTTPStatus
import json
import os
import subprocess
import tempfile
import time
from typing import Any

from google import genai
from google.genai import errors
from prefect.flows import Flow
from prefect.client.schemas import FlowRun, State
from pydantic import ValidationError

from prefect.task_runners import ConcurrentTaskRunner
from google.genai.types import (
    File,
    FinishReason,
    GenerateContentConfig,
    GoogleSearch,
    ThinkingConfig,
    Tool,
)
from processing_pipeline.postgres_client import PostgresClient
from processing_pipeline.local_storage import LocalStorage
from processing_pipeline.processing_utils import (
    get_safety_settings,
    postprocess_snippet,
)
from processing_pipeline.constants import (
    GeminiCLIEventType,
    GeminiModel,
    ProcessingStatus,
    PromptStage,
)
from processing_pipeline.stage_3_models import Stage3Output
from utils import optional_flow, optional_task


@optional_task(log_prints=True, retries=3)
def fetch_a_specific_snippet_from_supabase(supabase_client, snippet_id):
    response = supabase_client.get_snippet_by_id(
        id=snippet_id,
        select='*, audio_file(radio_station_name, radio_station_code, location_state, location_city, recorded_at, recording_day_of_week), stage_1_llm_response("detection_result")',
    )
    if response:
        return response
    else:
        print(f"Snippet with id {snippet_id} not found")
        return None


@optional_task(log_prints=True, retries=3)
def fetch_a_new_snippet_from_supabase(supabase_client):
    return __fetch_a_new_snippet_from_supabase(supabase_client)


def __fetch_a_new_snippet_from_supabase(supabase_client):
    response = supabase_client.get_a_new_snippet_and_reserve_it()
    if response:
        print(f"Found a new snippet: {response['id']}")
        return response
    else:
        print("No new snippets found")
        return None


@optional_task(log_prints=True, retries=3)
def download_audio_file_from_s3(storage_client, file_path):
    return __download_audio_file_from_s3(storage_client, file_path)


def __download_audio_file_from_s3(storage_client, file_path):
    file_name = os.path.basename(file_path)
    storage_client.download_file(None, file_path, file_name)
    return file_name


@optional_task(log_prints=True, retries=3)
def update_snippet_in_supabase(
    supabase_client,
    snippet_id,
    gemini_response,
    grounding_metadata,
    thought_summaries,
    analyzed_by,
    status,
    error_message,
    stage_3_prompt_version_id=None,
):
    supabase_client.update_snippet(
        id=snippet_id,
        transcription=gemini_response["transcription"],
        translation=gemini_response["translation"],
        title=gemini_response["title"],
        summary=gemini_response["summary"],
        explanation=gemini_response["explanation"],
        disinformation_categories=gemini_response["disinformation_categories"],
        keywords_detected=gemini_response["keywords_detected"],
        language=gemini_response["language"],
        confidence_scores=gemini_response["confidence_scores"],
        emotional_tone=gemini_response["emotional_tone"],
        context=gemini_response["context"],
        political_leaning=gemini_response["political_leaning"],
        grounding_metadata=grounding_metadata,
        thought_summaries=thought_summaries,
        analyzed_by=analyzed_by,
        status=status,
        error_message=error_message,
        stage_3_prompt_version_id=stage_3_prompt_version_id,
    )


@optional_task(log_prints=True)
def get_metadata(snippet):
    return __get_metadata(snippet)


def __get_metadata(snippet):
    snippet_uuid = snippet["id"]
    flagged_snippets = snippet["stage_1_llm_response"]["detection_result"]["flagged_snippets"]
    metadata = {}
    for flagged_snippet in flagged_snippets:
        if flagged_snippet["uuid"] == snippet_uuid:
            metadata = flagged_snippet
            try:
                # Handle escaped unicode characters in the transcription
                metadata["transcription"] = flagged_snippet["transcription"].encode("latin-1").decode("unicode-escape")
            except (UnicodeError, AttributeError) as e:
                # Fallback to original transcription if decoding fails
                print(f"Warning: Failed to decode transcription: {e}")
                metadata["transcription"] = flagged_snippet["transcription"]

    audio_file = snippet["audio_file"]
    recorded_at = datetime.strptime(snippet["recorded_at"], "%Y-%m-%dT%H:%M:%S+00:00")
    audio_file["recorded_at"] = recorded_at.strftime("%B %-d, %Y %-I:%M %p")
    audio_file["recording_day_of_week"] = recorded_at.strftime("%A")
    audio_file["time_zone"] = "UTC"
    metadata["additional_info"] = audio_file

    del metadata["start_time"]
    del metadata["end_time"]

    # TODO: Add these fields back once we've fixed the pipeline
    del metadata["explanation"]
    del metadata["keywords_detected"]

    metadata["start_time"] = snippet["start_time"].split(":", 1)[1]
    metadata["end_time"] = snippet["end_time"].split(":", 1)[1]
    metadata["duration"] = snippet["duration"].split(":", 1)[1]

    return metadata


@optional_task(log_prints=True)
def analyze_snippet(gemini_key, audio_file, metadata, prompt_version: dict):
    main_model = GeminiModel.GEMINI_2_5_PRO
    fallback_model = GeminiModel.GEMINI_FLASH_LATEST

    try:
        print(f"Attempting analysis with {main_model}")
        analyzing_response = Stage3Executor.run(
            gemini_key=gemini_key,
            model_name=main_model,
            audio_file=audio_file,
            metadata=metadata,
            prompt_version=prompt_version,
        )
        return {
            **analyzing_response,
            "analyzed_by": main_model,
        }
    except errors.ServerError as e:
        print(f"Server error with {main_model} (code {e.code}): {e.message}")
        print(f"Falling back to {fallback_model}")
        analyzing_response = Stage3Executor.run(
            gemini_key=gemini_key,
            model_name=fallback_model,
            audio_file=audio_file,
            metadata=metadata,
            prompt_version=prompt_version,
        )
        return {
            **analyzing_response,
            "analyzed_by": fallback_model,
        }
    except errors.ClientError as e:
        if e.code in [HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN]:
            print(f"Auth error with {main_model} (code {e.code}): {e.message}")
            raise
        else:
            print(f"Client error with {main_model} (code {e.code}): {e.message}")
            print(f"Falling back to {fallback_model}")
            analyzing_response = Stage3Executor.run(
                gemini_key=gemini_key,
                model_name=fallback_model,
                audio_file=audio_file,
                metadata=metadata,
                prompt_version=prompt_version,
            )
            return {
                **analyzing_response,
                "analyzed_by": fallback_model,
            }


@optional_task(log_prints=True)
def process_snippet(supabase_client, snippet, local_file, gemini_key, skip_review: bool, prompt_version: dict):
    print(f"Processing snippet: {local_file}")

    try:
        metadata = get_metadata(snippet)
        print(f"Metadata:\n{json.dumps(metadata, indent=2, ensure_ascii=False)}")

        analyzing_response = analyze_snippet(
            gemini_key=gemini_key,
            audio_file=local_file,
            metadata=metadata,
            prompt_version=prompt_version,
        )

        status = ProcessingStatus.PROCESSED if skip_review else ProcessingStatus.READY_FOR_REVIEW
        update_snippet_in_supabase(
            supabase_client=supabase_client,
            snippet_id=snippet["id"],
            gemini_response=analyzing_response["response"],
            grounding_metadata=analyzing_response["grounding_metadata"],
            thought_summaries=analyzing_response["thought_summaries"],
            analyzed_by=analyzing_response["analyzed_by"],
            status=status,
            error_message=None,
            stage_3_prompt_version_id=prompt_version["id"],
        )

        if skip_review:
            postprocess_snippet(
                supabase_client, snippet["id"], analyzing_response["response"]["disinformation_categories"]
            )

        print(f"Processing completed for audio file {local_file} - snippet ID: {snippet['id']}")

    except Exception as e:
        print(f"Failed to process {local_file}: {e}")
        supabase_client.set_snippet_status(snippet["id"], ProcessingStatus.ERROR, str(e))


def reset_snippet_status_hook(flow: Flow, flow_run: FlowRun, state: State):
    snippet_ids = flow_run.parameters.get("snippet_ids", None)

    if not snippet_ids:
        return

    supabase_client = PostgresClient()
    for snippet_id in snippet_ids:
        snippet = fetch_a_specific_snippet_from_supabase(supabase_client, snippet_id)
        if snippet and snippet["status"] == ProcessingStatus.PROCESSING:
            supabase_client.set_snippet_status(snippet_id, ProcessingStatus.NEW)


@optional_flow(
    name="Stage 3: In-depth Analysis",
    log_prints=True,
    task_runner=ConcurrentTaskRunner,
    on_crashed=[reset_snippet_status_hook],
    on_cancellation=[reset_snippet_status_hook],
)
def in_depth_analysis(snippet_ids, skip_review, repeat):
    # Setup S3 Client
    storage_client = LocalStorage()

    # Setup Gemini Key
    GEMINI_KEY = os.getenv("GOOGLE_GEMINI_KEY")

    # Setup PostgreSQL client
    supabase_client = PostgresClient()

    # Load prompt version
    prompt_version = supabase_client.get_active_prompt(PromptStage.STAGE_3)

    if snippet_ids:
        for id in snippet_ids:
            snippet = fetch_a_specific_snippet_from_supabase(supabase_client, id)
            if snippet:
                supabase_client.set_snippet_status(snippet["id"], ProcessingStatus.PROCESSING)
                print(f"Found the snippet: {snippet['id']}")
                local_file = download_audio_file_from_s3(storage_client, snippet["file_path"])

                # Process the snippet
                process_snippet(
                    supabase_client,
                    snippet,
                    local_file,
                    GEMINI_KEY,
                    skip_review=skip_review,
                    prompt_version=prompt_version,
                )

                print(f"Delete the downloaded snippet clip: {local_file}")
                os.remove(local_file)
    else:
        while True:
            snippet = fetch_a_new_snippet_from_supabase(supabase_client)  # TODO: Retry failed snippets (status: Error)

            if snippet:
                local_file = download_audio_file_from_s3(storage_client, snippet["file_path"])

                # Process the snippet
                process_snippet(
                    supabase_client,
                    snippet,
                    local_file,
                    GEMINI_KEY,
                    skip_review=skip_review,
                    prompt_version=prompt_version,
                )

                print(f"Delete the downloaded snippet clip: {local_file}")
                os.remove(local_file)

            # Stop the flow if we're not meant to repeat the process
            if not repeat:
                break

            if snippet:
                sleep_time = 2
            else:
                sleep_time = 60

            print(f"Sleep for {sleep_time} seconds before the next iteration")
            time.sleep(sleep_time)


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
        analysis_result = None
        uploaded_audio_file = None

        try:
            user_prompt_with_file = user_prompt + f"Here is the audio file attached: @{os.path.basename(audio_file)}"
            analysis_result = cls.__analyze_with_custom_search(
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

            analysis_result = cls.__analyze_with_google_search_grounding(
                client,
                model_name,
                user_prompt,
                uploaded_audio_file,
                system_instruction=prompt_version["system_instruction"],
            )

        try:
            analysis_text = analysis_result["text"]
            grounding_metadata = analysis_result["grounding_metadata"]
            # SDK method returns thought_summaries from thinking_config, CLI method doesn't
            thought_summaries_from_api = analysis_result.get("thought_summaries")

            # Try to validate with Pydantic model first
            validated_output = cls.__validate_with_pydantic(analysis_text)

            if validated_output:
                # Use thought_summaries from API if available (SDK), otherwise from JSON response (CLI)
                thought_summaries = thought_summaries_from_api or validated_output.get("thought_summaries")
                return {
                    "response": validated_output,
                    "grounding_metadata": grounding_metadata,
                    "thought_summaries": thought_summaries,
                }

            # Step 2: Structure with response_schema (if validation failed)
            structured_output = cls.__structure_with_schema(client, analysis_text, prompt_version["output_schema"])
            thought_summaries = thought_summaries_from_api or structured_output.get("thought_summaries")
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
            dict: {"text": str, "grounding_metadata": str|None, "thought_summaries": str|None}

        Raises:
            RuntimeError: If CLI execution fails (for fallback to SDK method)
        """
        print("Analyzing with Gemini CLI (custom search)...")

        events: list[dict[str, Any]] = []
        final_response = ""
        tool_calls: dict[str, dict[str, Any]] = {}  # Dict to match tool_use with tool_result by tool_id
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

                    # Capture tool use events
                    if event.get("type") == GeminiCLIEventType.TOOL_USE:
                        tool_id = event.get("tool_id")
                        tool_name = event.get("tool_name")
                        parameters = event.get("parameters")

                        if tool_id in tool_calls:
                            tool_calls[tool_id]["tool_name"] = tool_name
                            tool_calls[tool_id]["parameters"] = parameters
                        else:
                            tool_calls[tool_id] = {
                                "tool_id": tool_id,
                                "tool_name": tool_name,
                                "parameters": parameters,
                                "output": None,
                                "status": None,
                            }

                    # Capture tool result events and pair with tool_use
                    if event.get("type") == GeminiCLIEventType.TOOL_RESULT:
                        tool_id = event.get("tool_id")
                        output = event.get("output")
                        status = event.get("status")

                        if tool_id in tool_calls:
                            tool_calls[tool_id]["output"] = output
                            tool_calls[tool_id]["status"] = status
                        else:
                            tool_calls[tool_id] = {
                                "tool_id": tool_id,
                                "tool_name": None,
                                "parameters": None,
                                "output": output,
                                "status": status,
                            }
                except json.JSONDecodeError:
                    pass

            if result.returncode != 0:
                raise RuntimeError(f"Gemini CLI exited with code {result.returncode}: {result.stderr}")

            if not final_response:
                raise RuntimeError("Gemini CLI returned no response")

            # Convert tool_calls dict to list and serialize as JSON
            tool_calls_list = list(tool_calls.values()) if tool_calls else None
            return {
                "text": final_response,
                "grounding_metadata": json.dumps(tool_calls_list) if tool_calls_list else None,
            }

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

        grounding_metadata = (
            response.candidates[0].grounding_metadata.model_dump_json(indent=2) if response.candidates else None
        )

        if not response.text:
            finish_reason = response.candidates[0].finish_reason if response.candidates else None

            if finish_reason == FinishReason.MAX_TOKENS:
                raise ValueError("The response from Gemini was too long and was cut off in step 1.")

            print(f"Response finish reason: {finish_reason}")
            raise ValueError("No response from Gemini in step 1.")

        return {
            "text": response.text,
            "grounding_metadata": grounding_metadata,
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
