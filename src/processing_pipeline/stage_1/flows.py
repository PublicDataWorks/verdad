from datetime import datetime
import json
import os
import time

import boto3
from google import genai
from prefect.flows import Flow
from prefect.client.schemas import FlowRun, State
from prefect.task_runners import ConcurrentTaskRunner

from processing_pipeline.constants import GeminiModel, ProcessingStatus, PromptStage

from processing_pipeline.stage_1.tasks import (
    delete_stage_1_llm_responses,
    disinformation_detection_with_gemini,
    download_audio_file_from_s3,
    fetch_a_new_audio_file_from_supabase,
    fetch_audio_file_by_id,
    fetch_stage_1_llm_response_by_id,
    get_audio_file_metadata,
    process_audio_file,
    reset_status_of_audio_files,
    reset_status_of_stage_1_llm_response,
    set_audio_file_status,
    set_status_of_stage_1_llm_response,
    transcribe_audio_file_with_timestamp_with_gemini,
    update_stage_1_llm_response_detection_result,
    update_stage_1_llm_response_timestamped_transcription,
)
from processing_pipeline.supabase_utils import SupabaseClient
from utils import optional_flow


def reset_audio_file_status_hook(flow: Flow, flow_run: FlowRun, state: State):
    audio_file_id = flow_run.parameters.get("audio_file_id", None)

    if not audio_file_id:
        return

    supabase_client = SupabaseClient(supabase_url=os.getenv("SUPABASE_URL"), supabase_key=os.getenv("SUPABASE_KEY"))
    audio_file = supabase_client.get_audio_file_by_id(audio_file_id)
    if audio_file and audio_file.get("status") == ProcessingStatus.PROCESSING:
        set_audio_file_status(supabase_client, audio_file_id, ProcessingStatus.NEW)


@optional_flow(
    name="Stage 1: Initial Disinformation Detection",
    log_prints=True,
    task_runner=ConcurrentTaskRunner,
    on_crashed=[reset_audio_file_status_hook],
    on_cancellation=[reset_audio_file_status_hook],
)
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

    # Setup Gemini client
    gemini_client = _create_gemini_client()

    # Load prompt versions
    initial_transcription_prompt_version = supabase_client.get_active_prompt(PromptStage.STAGE_1_INITIAL_TRANSCRIPTION)
    initial_detection_prompt_version = supabase_client.get_active_prompt(PromptStage.STAGE_1_INITIAL_DETECTION)
    transcription_prompt_version = supabase_client.get_active_prompt(PromptStage.GEMINI_TIMESTAMPED_TRANSCRIPTION)
    detection_prompt_version = supabase_client.get_active_prompt(PromptStage.STAGE_1)

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
            process_audio_file(
                supabase_client=supabase_client,
                gemini_client=gemini_client,
                audio_file=audio_file,
                local_file=local_file,
                initial_transcription_prompt_version=initial_transcription_prompt_version,
                initial_detection_prompt_version=initial_detection_prompt_version,
                transcription_prompt_version=transcription_prompt_version,
                detection_prompt_version=detection_prompt_version,
            )
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

    # Setup Gemini client
    gemini_client = _create_gemini_client()

    # Load prompt version
    detection_prompt_version = supabase_client.get_active_prompt(PromptStage.STAGE_1)

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

                print("Processing the timestamped transcription with Gemini Flash Latest")
                detection_result = disinformation_detection_with_gemini(
                    gemini_client=gemini_client,
                    timestamped_transcription=timestamped_transcription["timestamped_transcription"],
                    metadata=metadata,
                    prompt_version=detection_prompt_version,
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

    # Setup Gemini client
    gemini_client = _create_gemini_client()

    # Load prompt versions
    transcription_prompt_version = supabase_client.get_active_prompt(PromptStage.GEMINI_TIMESTAMPED_TRANSCRIPTION)
    detection_prompt_version = supabase_client.get_active_prompt(PromptStage.STAGE_1)

    for id in stage_1_llm_response_ids:
        stage_1_llm_response = fetch_stage_1_llm_response_by_id(supabase_client, id)

        if stage_1_llm_response:
            print(f"Found stage 1 llm response {id}")

            audio_file = stage_1_llm_response["audio_file"]
            local_file = download_audio_file_from_s3(s3_client, audio_file["file_path"])
            metadata = get_audio_file_metadata(audio_file)

            initial_detection_result = stage_1_llm_response["initial_detection_result"] or {}
            flagged_snippets = initial_detection_result.get("flagged_snippets", [])

            if len(flagged_snippets) == 0:
                print("No flagged snippets found during the initial detection phase.")
            else:
                # Timestamped transcription
                transcriptor = GeminiModel.GEMINI_FLASH_LATEST
                timestamped_transcription = transcribe_audio_file_with_timestamp_with_gemini(
                    gemini_client=gemini_client,
                    audio_file=local_file,
                    prompt_version=transcription_prompt_version,
                    model_name=transcriptor,
                )
                update_stage_1_llm_response_timestamped_transcription(
                    supabase_client, id, timestamped_transcription, transcriptor
                )

                # Main detection
                detection_result = disinformation_detection_with_gemini(
                    gemini_client=gemini_client,
                    timestamped_transcription=timestamped_transcription["timestamped_transcription"],
                    metadata=metadata,
                    prompt_version=detection_prompt_version,
                    model_name=GeminiModel.GEMINI_FLASH_LATEST,
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


def _create_gemini_client() -> genai.Client | None:
    gemini_key = os.getenv("GOOGLE_GEMINI_KEY")
    return genai.Client(api_key=gemini_key) if gemini_key else None
