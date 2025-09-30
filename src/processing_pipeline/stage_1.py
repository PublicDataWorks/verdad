from datetime import datetime
import os
import time
import json
import boto3
import uuid
from google import genai
from google.genai.types import (
    GenerateContentConfig,
    HarmBlockThreshold,
    HarmCategory,
    SafetySetting,
    ThinkingConfig,
    FinishReason,
)
from google.genai.errors import ServerError
from openai import OpenAI
from prefect.task_runners import ConcurrentTaskRunner
from processing_pipeline.timestamped_transcription_generator import TimestampedTranscriptionGenerator
from processing_pipeline.stage_1_preprocess import (
    Stage1PreprocessDetectionExecutor,
    Stage1PreprocessTranscriptionExecutor,
)
from processing_pipeline.supabase_utils import SupabaseClient
from processing_pipeline.constants import (
    GeminiModel,
    get_system_instruction_for_stage_1,
    get_output_schema_for_stage_1,
    get_detection_prompt_for_stage_1,
)
from processing_pipeline.gemini_2_5_pro_transcription_generator import Gemini25ProTranscriptionGenerator
from utils import optional_flow, optional_task


@optional_task(log_prints=True, retries=3)
def fetch_a_new_audio_file_from_supabase(supabase_client):
    response = supabase_client.get_a_new_audio_file_and_reserve_it()
    if response:
        print(f"Found a new audio file:\n{json.dumps(response, indent=2)}\n")
        return response
    else:
        print("No new audio files found")
        return None


@optional_task(log_prints=True, retries=3)
def fetch_audio_file_by_id(supabase_client, audio_file_id):
    response = supabase_client.get_audio_file_by_id(audio_file_id)
    if response:
        return response
    else:
        print(f"Audio file with id {audio_file_id} not found")
        return None


@optional_task(log_prints=True, retries=3)
def fetch_stage_1_llm_response_by_id(supabase_client, stage_1_llm_response_id):
    response = supabase_client.get_stage_1_llm_response_by_id(
        id=stage_1_llm_response_id,
        select="*, audio_file(radio_station_name, radio_station_code, location_state, location_city, recorded_at, recording_day_of_week, file_path)",
    )
    if response:
        return response
    else:
        print(f"Stage 1 LLM response with id {stage_1_llm_response_id} not found")
        return None


@optional_task(log_prints=True, retries=3)
def download_audio_file_from_s3(s3_client, file_path):
    return __download_audio_file_from_s3(s3_client, file_path)


def __download_audio_file_from_s3(s3_client, file_path):
    r2_bucket_name = os.getenv("R2_BUCKET_NAME")
    file_name = os.path.basename(file_path)
    s3_client.download_file(r2_bucket_name, file_path, file_name)
    return file_name


@optional_task(log_prints=True, retries=3)
def transcribe_audio_file_with_gemini(audio_file, model_name=GeminiModel.GEMINI_FLASH_LATEST) -> str:
    print(f"Transcribing the audio file {audio_file} with {model_name}")
    gemini_key = os.getenv("GOOGLE_GEMINI_KEY")
    response = Stage1PreprocessTranscriptionExecutor.run(audio_file, gemini_key, model_name)
    return response["transcription"]


@optional_task(log_prints=True)
def transcribe_audio_file_with_open_ai_whisper_1(audio_file):
    print(f"Transcribing the audio file {audio_file} with OpenAI Whisper 1")
    return __transcribe_audio_file_with_open_ai_whisper_1(audio_file)


def __transcribe_audio_file_with_open_ai_whisper_1(audio_file):
    # TODO: Use "Prompt parameter" to improve the reliability of Whisper
    # TODO: Post-process the transcription using LLMs
    # TODO: Ask Whisper to include punctuation and filter words in the transcript
    # See more: https://platform.openai.com/docs/guides/speech-to-text/improving-reliability

    if not os.getenv("OPENAI_API_KEY"):
        raise ValueError("OpenAI API key was not set!")

    # Setup Open AI Client
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    # Transcribe the audio file
    response = client.audio.transcriptions.create(
        model="whisper-1",
        file=open(audio_file, "rb"),
        response_format="verbose_json",
        timestamp_granularities=["segment"],
    )

    # Format the transcription ouput
    timestamped_transcription = ""
    for segment in response.segments:
        # Calculate minutes and seconds from segment start time
        minutes = int(segment.start) // 60
        seconds = int(segment.start) % 60
        # Format start time as "MM:SS"
        start_time = f"{minutes:02d}:{seconds:02d}"
        timestamped_transcription += f"[{start_time}] {segment.text}\n"

    return {
        "language": response.language,
        "duration": int(response.duration),
        "transcription": response.text,
        "timestamped_transcription": timestamped_transcription,
    }


@optional_task(log_prints=True)
def transcribe_audio_file_with_gemini_2_5_pro(audio_file):
    print(f"Transcribing the audio file {audio_file} with Gemini 2.5 Pro")
    gemini_key = os.getenv("GOOGLE_GEMINI_KEY")
    timestamped_transcription = Gemini25ProTranscriptionGenerator.run(audio_file, gemini_key)
    return {"timestamped_transcription": timestamped_transcription}


@optional_task(log_prints=True)
def transcribe_audio_file_with_custom_timestamped_transcription_generator(audio_file):
    print(f"Transcribing the audio file {audio_file} with the custom timestamped-transcription-generator")
    gemini_key = os.getenv("GOOGLE_GEMINI_KEY")
    timestamped_transcription = TimestampedTranscriptionGenerator.run(audio_file, gemini_key, 10)
    return {"timestamped_transcription": timestamped_transcription}


@optional_task(log_prints=True)
def initial_disinformation_detection_with_gemini(
    initial_transcription,
    metadata,
    model_name=GeminiModel.GEMINI_FLASH_LATEST,
):
    gemini_key = os.getenv("GOOGLE_GEMINI_KEY")
    response = Stage1PreprocessDetectionExecutor.run(gemini_key, model_name, initial_transcription, metadata)
    return response


@optional_task(log_prints=True)
def disinformation_detection_with_gemini(
    timestamped_transcription,
    metadata,
    model_name=GeminiModel.GEMINI_FLASH_LATEST,
):
    gemini_key = os.getenv("GOOGLE_GEMINI_KEY")
    response = Stage1Executor.run(
        gemini_key=gemini_key,
        model_name=model_name,
        timestamped_transcription=timestamped_transcription,
        metadata=metadata,
    )
    flagged_snippets = response["flagged_snippets"]

    # Generate a uuid for each flagged snippet
    for snippet in flagged_snippets:
        snippet["uuid"] = str(uuid.uuid4())

    return response


@optional_task(log_prints=True, retries=3)
def insert_stage_1_llm_response(
    supabase_client,
    audio_file_id,
    initial_transcription,
    initial_detection_result,
    transcriptor,
    timestamped_transcription,
    detection_result,
    status,
):
    supabase_client.insert_stage_1_llm_response(
        audio_file_id=audio_file_id,
        initial_transcription=initial_transcription,
        initial_detection_result=initial_detection_result,
        transcriptor=transcriptor,
        timestamped_transcription=timestamped_transcription,
        detection_result=detection_result,
        status=status,
    )


@optional_task(log_prints=True, retries=3)
def set_audio_file_status_success(supabase_client, audio_file_id):
    supabase_client.set_audio_file_status(audio_file_id, "Processed")


@optional_task(log_prints=True, retries=3)
def set_audio_file_status_error(supabase_client, audio_file_id, error_message):
    supabase_client.set_audio_file_status(audio_file_id, "Error", error_message)


@optional_task(log_prints=True)
def process_audio_file(supabase_client, audio_file, local_file):
    try:
        # Transcribe the audio file with Google Gemini 2.5 Flash
        initial_transcription = transcribe_audio_file_with_gemini(local_file)

        # Get metadata of the transcription
        recorded_at = datetime.strptime(audio_file["recorded_at"], "%Y-%m-%dT%H:%M:%S+00:00")
        metadata = {
            "radio_station_name": audio_file["radio_station_name"],
            "radio_station_code": audio_file["radio_station_code"],
            "location": {"state": audio_file["location_state"], "city": audio_file["location_city"]},
            "recorded_at": recorded_at.strftime("%B %-d, %Y %-I:%M %p"),
            "recording_day_of_week": recorded_at.strftime("%A"),
            "time_zone": "UTC",
        }

        # Detect disinformation from the initial transcription using Gemini 2.5 Flash
        initial_detection_result = initial_disinformation_detection_with_gemini(initial_transcription, metadata)
        print(f"Initial detection result:\n{json.dumps(initial_detection_result, indent=2)}\n")
        flag_snippets = initial_detection_result["flagged_snippets"]

        if len(flag_snippets) == 0:
            print(
                "No flagged snippets found during the initial detection, inserting the llm response with status 'Processed'"
            )
            insert_stage_1_llm_response(
                supabase_client=supabase_client,
                audio_file_id=audio_file["id"],
                initial_transcription=initial_transcription,
                initial_detection_result=initial_detection_result,
                transcriptor=None,
                timestamped_transcription=None,
                detection_result=None,
                status="Processed",
            )
        else:
            # Use Gemini 2.5 Pro for the timestamped transcription
            try:
                transcriptor = "gemini-2.5-pro"
                timestamped_transcription = transcribe_audio_file_with_gemini_2_5_pro(local_file)
            except ValueError | ServerError as e:
                print(
                    f"Failed to transcribe the audio file with Gemini 2.5 Pro: {e}\n"
                    "Falling back to the custom timestamped-transcript generator"
                )
                transcriptor = "custom"
                timestamped_transcription = transcribe_audio_file_with_custom_timestamped_transcription_generator(
                    local_file
                )

            print("Processing the timestamped transcription with Gemini Flash Latest (Main detection phase)")
            detection_result = disinformation_detection_with_gemini(
                timestamped_transcription=timestamped_transcription["timestamped_transcription"],
                metadata=metadata,
                model_name=GeminiModel.GEMINI_FLASH_LATEST,
            )
            print(f"Detection result:\n{json.dumps(detection_result, indent=2)}\n")

            flagged_snippets = detection_result["flagged_snippets"]

            if len(flagged_snippets) == 0:
                "No flagged snippets found, inserting the llm response with status 'Processed'"
                insert_stage_1_llm_response(
                    supabase_client=supabase_client,
                    audio_file_id=audio_file["id"],
                    initial_transcription=initial_transcription,
                    initial_detection_result=initial_detection_result,
                    transcriptor=transcriptor,
                    timestamped_transcription=timestamped_transcription,
                    detection_result=detection_result,
                    status="Processed",
                )
            else:
                "Flagged snippets found, inserting the llm response with status 'New'"
                insert_stage_1_llm_response(
                    supabase_client=supabase_client,
                    audio_file_id=audio_file["id"],
                    initial_transcription=initial_transcription,
                    initial_detection_result=initial_detection_result,
                    transcriptor=transcriptor,
                    timestamped_transcription=timestamped_transcription,
                    detection_result=detection_result,
                    status="New",
                )

        print(f"Processing completed for {local_file}")
        set_audio_file_status_success(supabase_client, audio_file["id"])

    except Exception as e:
        print(f"Failed to process audio file {local_file}: {e}")
        set_audio_file_status_error(supabase_client, audio_file["id"], str(e))


@optional_flow(name="Stage 1: Initial Disinformation Detection", log_prints=True, task_runner=ConcurrentTaskRunner)
def initial_disinformation_detection(audio_file_id, limit):
    # Setup S3 Client
    s3_client = boto3.client(
        "s3",
        endpoint_url=os.getenv("R2_ENDPOINT_URL"),
        aws_access_key_id=os.getenv("R2_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("R2_SECRET_ACCESS_KEY"),
    )

    # Setup Supabase client
    supabase_client = SupabaseClient(supabase_url=os.getenv("SUPABASE_URL"), supabase_key=os.getenv("SUPABASE_KEY"))

    # Track the number of audio files processed
    processed_audio_files = 0

    while True:
        if audio_file_id:
            audio_file = fetch_audio_file_by_id(supabase_client, audio_file_id)
        else:
            audio_file = fetch_a_new_audio_file_from_supabase(supabase_client)  # TODO: Retry failed audio files (Error)

        if audio_file:
            local_file = download_audio_file_from_s3(s3_client, audio_file["file_path"])

            # Process the audio file
            process_audio_file(supabase_client, audio_file, local_file)
            processed_audio_files += 1
            print(f"Processed {processed_audio_files}/{limit} audio files")

            print(f"Delete the downloaded audio file: {local_file}")
            os.remove(local_file)

        # Break the loop if:
        # 1. We're processing a specific audio file (audio_file_id was provided), or
        # 2. We've reached the limit of audio files to process
        if audio_file_id or processed_audio_files >= limit:
            break

        if audio_file:
            sleep_time = 2
        else:
            sleep_time = 60

        print(f"Sleep for {sleep_time} seconds before the next iteration")
        time.sleep(sleep_time)


@optional_task(log_prints=True, retries=3)
def update_stage_1_llm_response_detection_result(supabase_client, id, detection_result):
    supabase_client.update_stage_1_llm_response_detection_result(id, detection_result)


@optional_task(log_prints=True, retries=3)
def update_stage_1_llm_response_timestamped_transcription(supabase_client, id, timestamped_transcription, transcriptor):
    supabase_client.update_stage_1_llm_response_timestamped_transcription(id, timestamped_transcription, transcriptor)


@optional_task(log_prints=True, retries=3)
def reset_status_of_stage_1_llm_response(supabase_client, stage_1_llm_response_id):
    supabase_client.reset_stage_1_llm_response_status(stage_1_llm_response_id)


@optional_task(log_prints=True, retries=3)
def set_status_of_stage_1_llm_response(supabase_client, stage_1_llm_response_id, status, error_message=None):
    supabase_client.set_stage_1_llm_response_status(stage_1_llm_response_id, status, error_message)


@optional_task(log_prints=True, retries=3)
def reset_status_of_audio_files(supabase_client, audio_file_ids):
    print(f"Reseting the status of the audio files: {audio_file_ids}")
    supabase_client.reset_audio_file_status(audio_file_ids)


@optional_task(log_prints=True, retries=3)
def delete_stage_1_llm_responses(supabase_client, audio_file_ids):
    print(f"Deleting the stage 1 llm responses that are associated with the audio files: {audio_file_ids}")
    supabase_client.delete_stage_1_llm_responses(audio_file_ids)


@optional_flow(name="Stage 1: Undo Disinformation Detection", log_prints=True, task_runner=ConcurrentTaskRunner)
def undo_disinformation_detection(audio_file_ids):
    if not audio_file_ids:
        print("No audio file ids were provided!")
        return

    # Setup Supabase client
    supabase_client = SupabaseClient(supabase_url=os.getenv("SUPABASE_URL"), supabase_key=os.getenv("SUPABASE_KEY"))

    # Reset the status of the audio files
    reset_status_of_audio_files(supabase_client, audio_file_ids)

    # Delete the stage 1 llm responses that are associated with the audio files
    delete_stage_1_llm_responses(supabase_client, audio_file_ids)


@optional_flow(name="Stage 1: Redo Main Detection Phase", log_prints=True, task_runner=ConcurrentTaskRunner)
def redo_main_detection(stage_1_llm_response_ids):
    if not stage_1_llm_response_ids:
        print("No stage 1 llm response ids were provided!")
        return

    # Setup Supabase client
    supabase_client = SupabaseClient(supabase_url=os.getenv("SUPABASE_URL"), supabase_key=os.getenv("SUPABASE_KEY"))

    for id in stage_1_llm_response_ids:
        stage_1_llm_response = fetch_stage_1_llm_response_by_id(supabase_client, id)

        if stage_1_llm_response:
            print(f"Found stage 1 llm response {id}")

            # Get metadata of the transcription
            audio_file = stage_1_llm_response["audio_file"]
            recorded_at = datetime.strptime(audio_file["recorded_at"], "%Y-%m-%dT%H:%M:%S+00:00")
            metadata = {
                "radio_station_name": audio_file["radio_station_name"],
                "radio_station_code": audio_file["radio_station_code"],
                "location": {"state": audio_file["location_state"], "city": audio_file["location_city"]},
                "recorded_at": recorded_at.strftime("%B %-d, %Y %-I:%M %p"),
                "recording_day_of_week": recorded_at.strftime("%A"),
                "time_zone": "UTC",
            }

            initial_detection_result = stage_1_llm_response["initial_detection_result"] or {}
            flagged_snippets = initial_detection_result.get("flagged_snippets", [])

            if len(flagged_snippets) == 0:
                print("No flagged snippets found during the initial detection phase.")
            else:
                timestamped_transcription = stage_1_llm_response["timestamped_transcription"]

                print("Processing the timestamped transcription with Gemini 2.5 Pro")
                detection_result = disinformation_detection_with_gemini(
                    timestamped_transcription=timestamped_transcription["timestamped_transcription"],
                    metadata=metadata,
                )
                print(f"Detection result:\n{json.dumps(detection_result, indent=2)}\n")
                update_stage_1_llm_response_detection_result(supabase_client, id, detection_result)

                # Reset the stage-1 LLM response status to New, error_message to None
                reset_status_of_stage_1_llm_response(supabase_client, id)

            print(f"Processing completed for stage 1 llm response {id}")


@optional_flow(name="Stage 1: Regenerate Timestamped Transcript", log_prints=True, task_runner=ConcurrentTaskRunner)
def regenerate_timestamped_transcript(stage_1_llm_response_ids):
    if not stage_1_llm_response_ids:
        print("No stage 1 llm response ids were provided!")
        return

    # Setup Supabase client
    supabase_client = SupabaseClient(supabase_url=os.getenv("SUPABASE_URL"), supabase_key=os.getenv("SUPABASE_KEY"))

    # Setup S3 Client
    s3_client = boto3.client(
        "s3",
        endpoint_url=os.getenv("R2_ENDPOINT_URL"),
        aws_access_key_id=os.getenv("R2_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("R2_SECRET_ACCESS_KEY"),
    )

    for id in stage_1_llm_response_ids:
        stage_1_llm_response = fetch_stage_1_llm_response_by_id(supabase_client, id)

        if stage_1_llm_response:
            print(f"Found stage 1 llm response {id}")

            # Get metadata of the transcription
            audio_file = stage_1_llm_response["audio_file"]
            local_file = download_audio_file_from_s3(s3_client, audio_file["file_path"])
            recorded_at = datetime.strptime(audio_file["recorded_at"], "%Y-%m-%dT%H:%M:%S+00:00")
            metadata = {
                "radio_station_name": audio_file["radio_station_name"],
                "radio_station_code": audio_file["radio_station_code"],
                "location": {"state": audio_file["location_state"], "city": audio_file["location_city"]},
                "recorded_at": recorded_at.strftime("%B %-d, %Y %-I:%M %p"),
                "recording_day_of_week": recorded_at.strftime("%A"),
                "time_zone": "UTC",
            }

            initial_detection_result = stage_1_llm_response["initial_detection_result"] or {}
            flagged_snippets = initial_detection_result.get("flagged_snippets", [])

            if len(flagged_snippets) == 0:
                print("No flagged snippets found during the initial detection phase.")
            else:
                try:
                    transcriptor = "gemini-1206"
                    timestamped_transcription = transcribe_audio_file_with_gemini_2_5_pro(local_file)
                except ValueError as e:
                    print(
                        f"Failed to transcribe the audio file with Gemini 2.5 Pro: {e}\n"
                        "Falling back to the custom timestamped-transcript generator"
                    )
                    transcriptor = "custom"
                    timestamped_transcription = transcribe_audio_file_with_custom_timestamped_transcription_generator(
                        local_file
                    )
                update_stage_1_llm_response_timestamped_transcription(
                    supabase_client, id, timestamped_transcription, transcriptor
                )

                print("Processing the timestamped transcription with Gemini 2.5 Pro")
                detection_result = disinformation_detection_with_gemini(
                    timestamped_transcription=timestamped_transcription["timestamped_transcription"],
                    metadata=metadata,
                )
                print(f"Detection result:\n{json.dumps(detection_result, indent=2)}\n")
                update_stage_1_llm_response_detection_result(supabase_client, id, detection_result)

                flagged_snippets = detection_result["flagged_snippets"]

                if len(flagged_snippets) == 0:
                    print(
                        "No flagged snippets found during the main detection phase.\n"
                        "Set the stage-1 LLM response status to Processed"
                    )
                    set_status_of_stage_1_llm_response(supabase_client, id, "Processed", None)
                else:
                    print(
                        "Flagged snippets found during the main detection phase.\n"
                        "Reset the stage-1 LLM response status to New, error_message to None"
                    )
                    reset_status_of_stage_1_llm_response(supabase_client, id)

            print(f"Processing completed for stage 1 llm response {id}")
            print(f"Delete the downloaded audio file: {local_file}")
            os.remove(local_file)


class Stage1Executor:

    SYSTEM_INSTRUCTION = get_system_instruction_for_stage_1()
    DETECTION_PROMPT = get_detection_prompt_for_stage_1()
    OUTPUT_SCHEMA = get_output_schema_for_stage_1()

    @classmethod
    def run(cls, gemini_key, model_name: GeminiModel, timestamped_transcription, metadata):
        if not gemini_key:
            raise ValueError("Google Gemini API key was not set!")

        client = genai.Client(api_key=gemini_key)

        # Prepare the user prompt
        user_prompt = (
            f"{cls.DETECTION_PROMPT}\n\nHere is the metadata of the transcription:\n\n{json.dumps(metadata, indent=2)}\n\n"
            f"Here is the timestamped transcription:\n\n{timestamped_transcription}"
        )

        result = client.models.generate_content(
            model=model_name,
            contents=[user_prompt],
            config=GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=cls.OUTPUT_SCHEMA,
                max_output_tokens=16384,
                system_instruction=cls.SYSTEM_INSTRUCTION,
                thinking_config=ThinkingConfig(thinking_budget=4096),
                safety_settings=[
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
                ],
            ),
        )

        if not result.parsed:
            finish_reason = result.candidates[0].finish_reason
            if finish_reason == FinishReason.MAX_TOKENS:
                raise ValueError("The response from Gemini was too long and was cut off.")
            print(f"Response finish reason: {finish_reason}")
            raise ValueError("No response from Gemini.")

        return result.parsed
