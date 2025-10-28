from datetime import datetime
import os
import time
from google import genai
import json
import boto3
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
    GeminiModel,
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
def process_snippet(supabase_client, snippet, local_file, gemini_key, skip_review: bool):
    try:
        print(f"Processing snippet: {local_file} with Gemini 2.5 Flash")

        metadata = get_metadata(snippet)
        print(f"Metadata:\n{json.dumps(metadata, indent=2)}")

        response, grounding_metadata = Stage3Executor.run(
            gemini_key=gemini_key,
            model_name=GeminiModel.GEMINI_FLASH_LATEST,
            audio_file=local_file,
            metadata=metadata,
        )

        if skip_review:
            update_snippet_in_supabase(
                supabase_client=supabase_client,
                snippet_id=snippet["id"],
                gemini_response=response,
                grounding_metadata=grounding_metadata,
                status="Processed",
                error_message=None,
            )

            postprocess_snippet(supabase_client, snippet["id"], response["disinformation_categories"])

        else:
            update_snippet_in_supabase(
                supabase_client=supabase_client,
                snippet_id=snippet["id"],
                gemini_response=response,
                grounding_metadata=grounding_metadata,
                status="Ready for review",
                error_message=None,
            )

        print(f"Processing completed for audio file {local_file} - snippet ID: {snippet['id']}")

    except Exception as e:
        print(f"Failed to process {local_file}: {e}")
        supabase_client.set_snippet_status(snippet["id"], "Error", str(e))


@optional_flow(name="Stage 3: In-depth Analysis", log_prints=True, task_runner=ConcurrentTaskRunner)
def in_depth_analysis(snippet_ids, repeat, skip_review=True):
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
                supabase_client.set_snippet_status(snippet["id"], "Processing")
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

        Performs two-stage processing with validation optimization:
        1. Step 1: Analyze audio with Google Search enabled
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

        # Upload the audio file and wait for it to finish processing
        uploaded_audio_file = client.files.upload(file=audio_file)
        while uploaded_audio_file.state.name == "PROCESSING":
            print("Processing the uploaded audio file...")
            time.sleep(1)
            uploaded_audio_file = client.files.get(name=uploaded_audio_file.name)

        # Prepare the user prompt
        user_prompt = (
            f"{cls.USER_PROMPT}\n\nHere is the metadata of the attached audio clip:\n{json.dumps(metadata, indent=2)}"
        )

        try:
            # Step 1: Analyze with Google Search
            analysis_text, grounding_metadata = cls.__analyze_with_search(
                client,
                model_name,
                user_prompt,
                uploaded_audio_file,
            )

            # Try to validate with Pydantic model first
            validated_output = cls.__validate_with_pydantic(analysis_text)

            if validated_output:
                return validated_output, grounding_metadata

            # Step 2: Structure with response_schema (if validation failed)
            return cls.__structure_with_schema(client, analysis_text), grounding_metadata
        finally:
            client.files.delete(name=uploaded_audio_file.name)

    @optional_task(log_prints=True, retries=3)
    @classmethod
    def __analyze_with_search(
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
                thinking_config=ThinkingConfig(thinking_budget=4096),
                safety_settings=get_safety_settings(),
            ),
        )

        grounding_metadata = str(response.candidates[0].grounding_metadata) if response.candidates else None

        if not response.text:
            finish_reason = response.candidates[0].finish_reason if response.candidates else None

            if finish_reason == FinishReason.MAX_TOKENS:
                raise ValueError("The response from Gemini was too long and was cut off in step 1.")

            print(f"Response finish reason: {finish_reason}")
            raise ValueError("No response from Gemini in step 1.")

        return response.text, grounding_metadata

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
