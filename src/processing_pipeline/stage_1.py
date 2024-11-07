import os
import time
import google.generativeai as genai
import json
import boto3
import uuid
from google.generativeai.types import HarmCategory, HarmBlockThreshold
from openai import OpenAI
from prefect import flow, task
from prefect.task_runners import ConcurrentTaskRunner
from stage_1_preprocess import Stage1PreprocessDetectionExecutor, Stage1PreprocessTranscriptionExecutor
from supabase_utils import SupabaseClient
from constants import (
    get_system_instruction_for_stage_1,
    get_output_schema_for_stage_1,
    get_detection_prompt_for_stage_1,
)


@task(log_prints=True, retries=3)
def fetch_a_new_audio_file_from_supabase(supabase_client):
    response = supabase_client.get_audio_files(status="New", limit=1)
    if response:
        return response[0]
    else:
        print("No new audio files found")
        return None


@task(log_prints=True, retries=3)
def fetch_audio_file_by_id(supabase_client, audio_file_id):
    response = supabase_client.get_audio_file_by_id(audio_file_id)
    if response:
        return response
    else:
        print(f"Audio file with id {audio_file_id} not found")
        return None


@task(log_prints=True, retries=3)
def fetch_stage_1_llm_response_by_id(supabase_client, stage_1_llm_response_id):
    response = supabase_client.get_stage_1_llm_response_by_id(
        id=stage_1_llm_response_id,
        select="*, audio_file(radio_station_name, radio_station_code, location_state, location_city, recorded_at, recording_day_of_week)",
    )
    if response:
        return response
    else:
        print(f"Stage 1 LLM response with id {stage_1_llm_response_id} not found")
        return None


@task(log_prints=True, retries=3)
def download_audio_file_from_s3(s3_client, file_path):
    return __download_audio_file_from_s3(s3_client, file_path)


def __download_audio_file_from_s3(s3_client, file_path):
    r2_bucket_name = os.getenv("R2_BUCKET_NAME")
    file_name = os.path.basename(file_path)
    s3_client.download_file(r2_bucket_name, file_path, file_name)
    return file_name


@task(log_prints=True)
def transcribe_audio_file_with_gemini_1_5_flash_002(audio_file):
    gemini_key = os.getenv("GOOGLE_GEMINI_KEY")
    response = Stage1PreprocessTranscriptionExecutor.run(audio_file, gemini_key)
    return json.loads(response)


@task(log_prints=True)
def transcribe_audio_file_with_open_ai_whisper_1(audio_file):
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


@task(log_prints=True)
def initial_disinformation_detection_with_gemini_1_5_pro_002(initial_transcription, metadata):
    gemini_key = os.getenv("GOOGLE_GEMINI_KEY")
    response = Stage1PreprocessDetectionExecutor.run(gemini_key, initial_transcription, metadata)
    return json.loads(response)


@task(log_prints=True)
def disinformation_detection_with_gemini_1_5_pro_002(timestamped_transcription, metadata):
    gemini_key = os.getenv("GOOGLE_GEMINI_KEY")
    response = Stage1Executor.run(
        gemini_key=gemini_key,
        timestamped_transcription=timestamped_transcription,
        metadata=metadata,
    )
    json_response = json.loads(response)
    flagged_snippets = json_response["flagged_snippets"]

    # Generate a uuid for each flagged snippet
    for snippet in flagged_snippets:
        snippet["uuid"] = str(uuid.uuid4())

    return json_response


@task(log_prints=True, retries=3)
def insert_stage_1_llm_response(
    supabase_client,
    audio_file_id,
    initial_transcription,
    initial_detection_result,
    openai_response,
    detection_result,
    status,
):
    supabase_client.insert_stage_1_llm_response(
        audio_file_id=audio_file_id,
        initial_transcription=initial_transcription,
        initial_detection_result=initial_detection_result,
        openai_response=openai_response,
        detection_result=detection_result,
        status=status,
    )


@task(log_prints=True)
def process_audio_file(supabase_client, audio_file, local_file):
    try:
        # Transcribe the audio file with Google Gemini 1.5 Flash 002
        flash_response = transcribe_audio_file_with_gemini_1_5_flash_002(local_file)
        initial_transcription = flash_response["transcription"]

        # Get metadata of the transcription
        metadata = {
            "radio_station_name": audio_file["radio_station_name"],
            "radio_station_code": audio_file["radio_station_code"],
            "location": {"state": audio_file["location_state"], "city": audio_file["location_city"]},
            "recorded_at": audio_file["recorded_at"],
            "recording_day_of_week": audio_file["recording_day_of_week"],
            "time_zone": "UTC",
        }

        # Detect disinformation from the initial transcription using Gemini 1.5 Pro 002
        initial_detection_result = initial_disinformation_detection_with_gemini_1_5_pro_002(
            initial_transcription, metadata
        )
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
                openai_response=None,
                detection_result=None,
                status="Processed",
            )
        else:
            # Transcribe the audio file with OpenAI Whisper 1
            openai_response = transcribe_audio_file_with_open_ai_whisper_1(local_file)

            print("Processing the timestamped transcription (from Whisper) with Gemini 1.5 Pro 002")
            detection_result = disinformation_detection_with_gemini_1_5_pro_002(
                timestamped_transcription=openai_response["timestamped_transcription"],
                metadata=metadata,
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
                    openai_response=openai_response,
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
                    openai_response=openai_response,
                    detection_result=detection_result,
                    status="New",
                )

        print(f"Processing completed for {local_file}")
        supabase_client.set_audio_file_status(audio_file["id"], "Processed")

    except Exception as e:
        print(f"Failed to process audio file {local_file}: {e}")
        supabase_client.set_audio_file_status(audio_file["id"], "Error", str(e))


@flow(name="Stage 1: Initial Disinformation Detection", log_prints=True, task_runner=ConcurrentTaskRunner)
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
            current_status = supabase_client.get_audio_file_status(audio_file["id"])
            if current_status == "Processing":
                # Oops, another worker is already processing this audio file before we reserve it
                print(f"Audio file {audio_file['id']} is already being processed by another worker")
                continue

            # Immediately set the audio file to Processing, so that other workers don't pick it up
            supabase_client.set_audio_file_status(audio_file["id"], "Processing")
            print(f"Found a new audio file:\n{json.dumps(audio_file, indent=2)}\n")

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


@task(log_prints=True, retries=3)
def update_stage_1_llm_response_detection_result(supabase_client, id, detection_result):
    supabase_client.update_stage_1_llm_response_detection_result(id, detection_result)


@flow(name="Stage 1: Rerun Main Detection Phase", log_prints=True, task_runner=ConcurrentTaskRunner)
def rerun_main_detection_phase(stage_1_llm_response_ids):
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
            metadata = {
                "radio_station_name": audio_file["radio_station_name"],
                "radio_station_code": audio_file["radio_station_code"],
                "location": {"state": audio_file["location_state"], "city": audio_file["location_city"]},
                "recorded_at": audio_file["recorded_at"],
                "recording_day_of_week": audio_file["recording_day_of_week"],
                "time_zone": "UTC",
            }

            initial_detection_result = stage_1_llm_response["initial_detection_result"] or {}
            flag_snippets = initial_detection_result.get("flagged_snippets", [])

            if len(flag_snippets) == 0:
                print("No flagged snippets found during the initial detection phase.")
            else:
                openai_response = stage_1_llm_response["timestamped_transcription"]

                print("Processing the timestamped transcription (from Whisper) with Gemini 1.5 Pro 002")
                detection_result = disinformation_detection_with_gemini_1_5_pro_002(
                    timestamped_transcription=openai_response["timestamped_transcription"],
                    metadata=metadata,
                )
                print(f"Detection result:\n{json.dumps(detection_result, indent=2)}\n")
                update_stage_1_llm_response_detection_result(supabase_client, id, detection_result)

            print(f"Processing completed for stage 1 llm response {id}")


class Stage1Executor:

    SYSTEM_INSTRUCTION = get_system_instruction_for_stage_1()
    DETECTION_PROMPT = get_detection_prompt_for_stage_1()
    OUTPUT_SCHEMA = get_output_schema_for_stage_1()

    @classmethod
    def run(cls, gemini_key, timestamped_transcription, metadata):
        if not gemini_key:
            raise ValueError("Google Gemini API key was not set!")

        genai.configure(api_key=gemini_key)
        model = genai.GenerativeModel(
            model_name="gemini-1.5-pro-002",
            system_instruction=cls.SYSTEM_INSTRUCTION,
        )

        # Prepare the user prompt
        user_prompt = (
            f"{cls.DETECTION_PROMPT}\n\nHere is the metadata of the transcription:\n\n{json.dumps(metadata, indent=2)}\n\n"
            f"Here is the timestamped transcription:\n\n{timestamped_transcription}"
        )

        result = model.generate_content(
            [user_prompt],
            generation_config=genai.GenerationConfig(
                response_mime_type="application/json", response_schema=cls.OUTPUT_SCHEMA
            ),
            safety_settings={
                HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
            },
        )
        return result.text
