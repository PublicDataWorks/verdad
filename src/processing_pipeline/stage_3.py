from datetime import datetime, timezone
from http import HTTPStatus
import json
import os
import subprocess
import time
from typing import Any

import boto3
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
from processing_pipeline.supabase_utils import SupabaseClient
from processing_pipeline.processing_utils import (
    get_safety_settings,
    postprocess_snippet,
)
from processing_pipeline.constants import (
    GeminiCLIEventType,
    GeminiModel,
    ProcessingStatus,
    get_system_instruction_for_stage_3,
    get_output_schema_for_stage_3,
    get_user_prompt_for_stage_3,
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
def download_audio_file_from_s3(s3_client, r2_bucket_name, file_path):
    return __download_audio_file_from_s3(s3_client, r2_bucket_name, file_path)


def __download_audio_file_from_s3(s3_client, r2_bucket_name, file_path):
    file_name = os.path.basename(file_path)
    s3_client.download_file(r2_bucket_name, file_path, file_name)
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
def analyze_snippet(gemini_key, audio_file, metadata):
    main_model = GeminiModel.GEMINI_2_5_PRO
    fallback_model = GeminiModel.GEMINI_FLASH_LATEST

    try:
        print(f"Attempting analysis with {main_model}")
        analyzing_response = Stage3Executor.run(
            gemini_key=gemini_key,
            model_name=main_model,
            audio_file=audio_file,
            metadata=metadata,
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
            )
            return {
                **analyzing_response,
                "analyzed_by": fallback_model,
            }


@optional_task(log_prints=True)
def process_snippet(supabase_client, snippet, local_file, gemini_key, skip_review: bool):
    print(f"Processing snippet: {local_file}")

    try:
        metadata = get_metadata(snippet)
        print(f"Metadata:\n{json.dumps(metadata, indent=2, ensure_ascii=False)}")

        analyzing_response = analyze_snippet(
            gemini_key=gemini_key,
            audio_file=local_file,
            metadata=metadata,
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

    supabase_client = SupabaseClient(supabase_url=os.getenv("SUPABASE_URL"), supabase_key=os.getenv("SUPABASE_KEY"))
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
    R2_BUCKET_NAME = os.getenv("R2_BUCKET_NAME")
    s3_client = boto3.client(
        "s3",
        endpoint_url=os.getenv("R2_ENDPOINT_URL"),
        aws_access_key_id=os.getenv("R2_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("R2_SECRET_ACCESS_KEY"),
    )

    # Setup Gemini Key
    GEMINI_KEY = os.getenv("GOOGLE_GEMINI_KEY")

    # Setup Supabase client
    supabase_client = SupabaseClient(supabase_url=os.getenv("SUPABASE_URL"), supabase_key=os.getenv("SUPABASE_KEY"))

    if snippet_ids:
        for id in snippet_ids:
            snippet = fetch_a_specific_snippet_from_supabase(supabase_client, id)
            if snippet:
                supabase_client.set_snippet_status(snippet["id"], ProcessingStatus.PROCESSING)
                print(f"Found the snippet: {snippet['id']}")
                local_file = download_audio_file_from_s3(s3_client, R2_BUCKET_NAME, snippet["file_path"])

                # Process the snippet
                process_snippet(supabase_client, snippet, local_file, GEMINI_KEY, skip_review=skip_review)

                print(f"Delete the downloaded snippet clip: {local_file}")
                os.remove(local_file)
    else:
        while True:
            snippet = fetch_a_new_snippet_from_supabase(supabase_client)  # TODO: Retry failed snippets (status: Error)

            if snippet:
                local_file = download_audio_file_from_s3(s3_client, R2_BUCKET_NAME, snippet["file_path"])

                # Process the snippet
                process_snippet(supabase_client, snippet, local_file, GEMINI_KEY, skip_review=skip_review)

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

    SYSTEM_INSTRUCTION = get_system_instruction_for_stage_3()
    USER_PROMPT = get_user_prompt_for_stage_3()
    OUTPUT_SCHEMA = get_output_schema_for_stage_3()
    SYSTEM_INSTRUCTION_PATH = "prompts/Stage_3_system_instruction.md"

    @classmethod
    def run(
        cls,
        gemini_key: str,
        model_name: GeminiModel,
        audio_file: str,
        metadata: dict,
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

        Returns:
            dict: Structured and validated analysis output
        """
        if not gemini_key:
            raise ValueError("Google Gemini API key was not set!")

        client = genai.Client(api_key=gemini_key)

        # Prepare the user prompt
        user_prompt = (
            f"{cls.USER_PROMPT}\n\n"
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
            )

        try:
            analysis_text = analysis_result["text"]
            grounding_metadata = analysis_result["grounding_metadata"]
            thought_summaries = analysis_result["thought_summaries"]

            # Try to validate with Pydantic model first
            validated_output = cls.__validate_with_pydantic(analysis_text)

            if validated_output:
                return {
                    "response": validated_output,
                    "grounding_metadata": grounding_metadata,
                    "thought_summaries": thought_summaries,
                }

            # Step 2: Structure with response_schema (if validation failed)
            return {
                "response": cls.__structure_with_schema(client, analysis_text),
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
        tool_outputs = ""
        timeout = 300

        env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", ""),
            "GEMINI_API_KEY": os.environ["GOOGLE_GEMINI_KEY"],
            "GEMINI_SYSTEM_MD": cls.SYSTEM_INSTRUCTION_PATH,
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

                    # Concatenate tool result outputs
                    if event.get("type") == GeminiCLIEventType.TOOL_RESULT:
                        output = event.get("output")
                        if output and isinstance(output, str):
                            tool_outputs += output
                except json.JSONDecodeError:
                    pass

            if result.returncode != 0:
                raise RuntimeError(f"Gemini CLI exited with code {result.returncode}: {result.stderr}")

            if not final_response:
                raise RuntimeError("Gemini CLI returned no response")

            return {
                "text": final_response,
                "grounding_metadata": tool_outputs if tool_outputs else None,
            }

        except subprocess.TimeoutExpired as e:
            raise RuntimeError(f"Gemini CLI timed out after {timeout} seconds") from e

    @optional_task(log_prints=True, retries=3)
    @classmethod
    def __analyze_with_google_search_grounding(
        cls,
        client: genai.Client,
        model_name: GeminiModel,
        user_prompt: str,
        uploaded_audio_file: File,
    ):
        """
        Step 1: Analyze audio with Google Search tool enabled.

        Returns:
            str: The response text from Gemini
        """
        print("Analyzing audio with web search...")

        response = client.models.generate_content(
            model=model_name,
            contents=[user_prompt, uploaded_audio_file],
            config=GenerateContentConfig(
                system_instruction=cls.SYSTEM_INSTRUCTION,
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
        """
        Attempts to validate the response text with the Pydantic model.

        Returns:
            dict: Validated and structured output if successful
            None: If validation fails
        """
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
    ):
        """
        Step 2: Structure the analysis results using response_schema.

        Returns:
            dict: Structured and validated output
        """
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
                response_schema=cls.OUTPUT_SCHEMA,
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
