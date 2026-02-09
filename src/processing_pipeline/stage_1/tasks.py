from datetime import datetime
import json
import os
import uuid

from google import genai
from openai import OpenAI

from processing_pipeline.constants import GeminiModel, ProcessingStatus
from processing_pipeline.stage_1.executors import (
    GeminiTimestampTranscriptionGenerator,
    Stage1Executor,
    Stage1PreprocessDetectionExecutor,
    Stage1PreprocessTranscriptionExecutor,
)
from processing_pipeline.supabase_utils import SupabaseClient
from utils import optional_task


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


@optional_task(log_prints=True)
def get_audio_file_metadata(audio_file):
    recorded_at = datetime.strptime(audio_file["recorded_at"], "%Y-%m-%dT%H:%M:%S+00:00")
    return {
        "radio_station_name": audio_file["radio_station_name"],
        "radio_station_code": audio_file["radio_station_code"],
        "location": {
            "state": audio_file["location_state"],
            "city": audio_file["location_city"],
        },
        "recorded_at": recorded_at.strftime("%B %-d, %Y %-I:%M %p"),
        "recording_day_of_week": recorded_at.strftime("%A"),
        "time_zone": "UTC",
    }


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


@optional_task(log_prints=True, retries=3)
def initial_transcription_with_gemini(
    gemini_client: genai.Client | None,
    audio_file: str,
    prompt_version: dict,
) -> str:
    print(f"Initial transcription for audio file {audio_file} using Gemini")
    if not gemini_client:
        raise ValueError("Gemini client is not provided")

    response = Stage1PreprocessTranscriptionExecutor.run(
        gemini_client=gemini_client,
        audio_file=audio_file,
        model_name=GeminiModel.GEMINI_FLASH_LATEST,
        prompt_version=prompt_version,
    )
    return response["transcription"]


@optional_task(log_prints=True, retries=3)
def initial_disinformation_detection_with_gemini(
    gemini_client: genai.Client | None,
    initial_transcription: str,
    metadata: dict,
    prompt_version: dict,
):
    print(f"Processing initial transcription with Gemini for disinformation detection")
    if not gemini_client:
        raise ValueError("Gemini client is not provided")

    response = Stage1PreprocessDetectionExecutor.run(
        gemini_client=gemini_client,
        model_name=GeminiModel.GEMINI_FLASH_LATEST,
        transcription=initial_transcription,
        metadata=metadata,
        prompt_version=prompt_version,
    )
    return response


@optional_task(log_prints=True, retries=3)
def transcribe_audio_file_with_timestamp_with_gemini(
    gemini_client: genai.Client | None,
    audio_file: str,
    prompt_version: dict,
    model_name=GeminiModel.GEMINI_FLASH_LATEST,
):
    print(f"Transcribing the audio file {audio_file} using {model_name}")
    if not gemini_client:
        raise ValueError("Gemini client is not provided")

    timestamped_transcription = GeminiTimestampTranscriptionGenerator.run(
        gemini_client=gemini_client,
        audio_file=audio_file,
        model_name=model_name,
        prompt_version=prompt_version,
        segment_length=20,
        batch_size=30,
    )
    return {"timestamped_transcription": timestamped_transcription}


@optional_task(log_prints=True, retries=3)
def disinformation_detection_with_gemini(
    gemini_client: genai.Client | None,
    timestamped_transcription: str,
    metadata: dict,
    prompt_version: dict,
    model_name=GeminiModel.GEMINI_FLASH_LATEST,
):
    print(f"Processing the timestamped transcription with {model_name}")
    if not gemini_client:
        raise ValueError("Gemini client is not provided")

    response = Stage1Executor.run(
        gemini_client=gemini_client,
        model_name=model_name,
        timestamped_transcription=timestamped_transcription,
        metadata=metadata,
        prompt_version=prompt_version,
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
    detection_prompt_version_id=None,
    transcription_prompt_version_id=None,
):
    supabase_client.insert_stage_1_llm_response(
        audio_file_id=audio_file_id,
        initial_transcription=initial_transcription,
        initial_detection_result=initial_detection_result,
        transcriptor=transcriptor,
        timestamped_transcription=timestamped_transcription,
        detection_result=detection_result,
        status=status,
        detection_prompt_version_id=detection_prompt_version_id,
        transcription_prompt_version_id=transcription_prompt_version_id,
    )


@optional_task(log_prints=True, retries=3)
def set_audio_file_status(supabase_client, audio_file_id, status: ProcessingStatus, error_message=None):
    supabase_client.set_audio_file_status(audio_file_id, status, error_message)


@optional_task(log_prints=True)
def process_audio_file(
    supabase_client: SupabaseClient,
    gemini_client: genai.Client | None,
    audio_file: dict,
    local_file: str,
    initial_transcription_prompt_version: dict,
    initial_detection_prompt_version: dict,
    transcription_prompt_version: dict,
    detection_prompt_version: dict,
):
    metadata = get_audio_file_metadata(audio_file)
    print(f"Metadata of the audio file:\n{json.dumps(metadata, indent=2)}\n")

    try:
        # Initial transcription
        initial_transcription = initial_transcription_with_gemini(
            gemini_client=gemini_client,
            audio_file=local_file,
            prompt_version=initial_transcription_prompt_version,
        )

        # Initial detection
        initial_detection_result = initial_disinformation_detection_with_gemini(
            gemini_client=gemini_client,
            initial_transcription=initial_transcription,
            metadata=metadata,
            prompt_version=initial_detection_prompt_version,
        )
        print(f"Initial detection result:\n{json.dumps(initial_detection_result, indent=2, ensure_ascii=False)}\n")

        flagged_snippets = initial_detection_result["flagged_snippets"]

        if len(flagged_snippets) == 0:
            print("No flagged snippets found during initial detection. Skipping timestamped transcription.")
            insert_stage_1_llm_response(
                supabase_client=supabase_client,
                audio_file_id=audio_file["id"],
                initial_transcription=initial_transcription,
                initial_detection_result=initial_detection_result,
                transcriptor=None,
                timestamped_transcription=None,
                detection_result=None,
                status="Processed",
                detection_prompt_version_id=None,
                transcription_prompt_version_id=None,
            )
        else:
            # Timestamped transcription
            transcriptor = GeminiModel.GEMINI_FLASH_LATEST
            timestamped_transcription = transcribe_audio_file_with_timestamp_with_gemini(
                gemini_client=gemini_client,
                audio_file=local_file,
                prompt_version=transcription_prompt_version,
                model_name=transcriptor,
            )

            # Main detection
            detection_result = disinformation_detection_with_gemini(
                gemini_client=gemini_client,
                timestamped_transcription=timestamped_transcription["timestamped_transcription"],
                metadata=metadata,
                prompt_version=detection_prompt_version,
                model_name=GeminiModel.GEMINI_FLASH_LATEST,
            )
            print(f"Main detection result:\n{json.dumps(detection_result, indent=2, ensure_ascii=False)}\n")

            main_flagged_snippets = detection_result["flagged_snippets"]

            if len(main_flagged_snippets) == 0:
                print("No flagged snippets found during main detection. Setting status to 'Processed'.")
                insert_stage_1_llm_response(
                    supabase_client=supabase_client,
                    audio_file_id=audio_file["id"],
                    initial_transcription=initial_transcription,
                    initial_detection_result=initial_detection_result,
                    transcriptor=transcriptor,
                    timestamped_transcription=timestamped_transcription,
                    detection_result=detection_result,
                    status="Processed",
                    detection_prompt_version_id=detection_prompt_version["id"],
                    transcription_prompt_version_id=transcription_prompt_version["id"],
                )
            else:
                print(f"Found {len(main_flagged_snippets)} flagged snippets during main detection. Setting status to 'New'.")
                insert_stage_1_llm_response(
                    supabase_client=supabase_client,
                    audio_file_id=audio_file["id"],
                    initial_transcription=initial_transcription,
                    initial_detection_result=initial_detection_result,
                    transcriptor=transcriptor,
                    timestamped_transcription=timestamped_transcription,
                    detection_result=detection_result,
                    status="New",
                    detection_prompt_version_id=detection_prompt_version["id"],
                    transcription_prompt_version_id=transcription_prompt_version["id"],
                )

        print(f"Processing completed for {local_file}")
        set_audio_file_status(supabase_client, audio_file["id"], ProcessingStatus.PROCESSED)

    except Exception as e:
        print(f"Failed to process audio file {local_file}: {e}")
        set_audio_file_status(supabase_client, audio_file["id"], ProcessingStatus.ERROR, str(e))


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
