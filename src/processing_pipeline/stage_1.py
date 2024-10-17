import os
import time
import google.generativeai as genai
import json
import boto3
from openai import OpenAI
from prefect import flow, task
from prefect.task_runners import ConcurrentTaskRunner
from supabase_utils import SupabaseClient
from constants import (
    get_system_instruction_for_stage_1,
    get_output_schema_for_stage_1,
    get_user_prompt_for_stage_1,
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
def download_audio_file_from_s3(s3_client, r2_bucket_name, file_path):
    return __download_audio_file_from_s3(s3_client, r2_bucket_name, file_path)


def __download_audio_file_from_s3(s3_client, r2_bucket_name, file_path):
    file_name = os.path.basename(file_path)
    s3_client.download_file(r2_bucket_name, file_path, file_name)
    return file_name


@task(log_prints=True, retries=3)
def insert_stage_1_llm_response_in_supabase(
    supabase_client, audio_file_id, openai_response
):
    return supabase_client.insert_stage_1_llm_response(audio_file_id, openai_response)


@task(log_prints=True, retries=3)
def update_stage_1_llm_response_in_supabase(supabase_client, id, flash_response, status):
    supabase_client.update_stage_1_llm_response(id, flash_response, status)


@task(log_prints=True)
def transcribe_audio_file(audio_file):
    return __transcribe_audio_file(audio_file)


def __transcribe_audio_file(audio_file):
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
        timestamp_granularities=["segment"]
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
def process_audio_file(supabase_client, audio_file, local_file, gemini_key):
    try:
        print(f"Transcribing audio file: {local_file} with OpenAI Whisper 1")
        openai_response = transcribe_audio_file(local_file)

        # Insert a new stage_1_llm_response with OpenAI Whisper 1 response
        llm_response = insert_stage_1_llm_response_in_supabase(supabase_client, audio_file["id"], openai_response)

        # Get metadata of the transcription and the transcription itself
        metadata={
            "radio_station_name": audio_file["radio_station_name"],
            "radio_station_code": audio_file["radio_station_code"],
            "location": {"state": audio_file["location_state"], "city": audio_file["location_city"]},
            "recorded_at": audio_file["recorded_at"],
            "recording_day_of_week": audio_file["recording_day_of_week"],
            "time_zone": "UTC",
        }
        timestamped_transcription = openai_response["timestamped_transcription"]

        print(f"Processing audio file: {local_file} with Gemini 1.5 Flash 002")
        flash_response = Stage1Executor.run(
            gemini_key=gemini_key,
            model_name="gemini-1.5-flash-002",
            timestamped_transcription=timestamped_transcription,
            metadata=metadata,
        )

        # Check if the response is a valid JSON
        flash_response = json.loads(flash_response)
        print(f"Gemini 1.5 Flash 002 Response:\n{json.dumps(flash_response, indent=2)}\n")

        flagged_snippets = flash_response["flagged_snippets"]
        if len(flagged_snippets) == 0:
            print("No flagged snippets found, marking the response as processed")
            update_stage_1_llm_response_in_supabase(
                supabase_client, llm_response["id"], flash_response, "Processed"
            )
        else:
            update_stage_1_llm_response_in_supabase(
                supabase_client, llm_response["id"], flash_response, "New"
            )

        print(f"Processing completed for {local_file}")
        supabase_client.set_audio_file_status(audio_file["id"], "Processed")

    except Exception as e:
        print(f"Failed to process audio file {local_file}: {e}")
        supabase_client.set_audio_file_status(audio_file["id"], "Error", str(e))


@flow(name="Stage 1: Initial Disinformation Detection", log_prints=True, task_runner=ConcurrentTaskRunner)
def initial_disinformation_detection(repeat):
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

    while True:
        audio_file = fetch_a_new_audio_file_from_supabase(supabase_client)  # TODO: Retry failed audio files (Error)
        if audio_file:
            # Immediately set the audio file to Processing, so that other workers don't pick it up
            supabase_client.set_audio_file_status(audio_file["id"], "Processing")

            print("Found a new audio file:")
            print(json.dumps(audio_file, indent=2))

            local_file = download_audio_file_from_s3(s3_client, R2_BUCKET_NAME, audio_file["file_path"])

            # Process the audio file
            process_audio_file(supabase_client, audio_file, local_file, GEMINI_KEY)

            print(f"Delete the downloaded audio file: {local_file}")
            os.remove(local_file)

        # Stop the flow if it should not be repeated
        if not repeat:
            break

        if audio_file:
            sleep_time = 2
        else:
            sleep_time = 30

        print(f"Sleep for {sleep_time} seconds before the next iteration")
        time.sleep(sleep_time)


class Stage1Executor:

    SYSTEM_INSTRUCTION = get_system_instruction_for_stage_1()
    USER_PROMPT = get_user_prompt_for_stage_1()
    OUTPUT_SCHEMA = get_output_schema_for_stage_1()

    @classmethod
    def run(cls, gemini_key, model_name, timestamped_transcription, metadata):
        if not gemini_key:
            raise ValueError("Google Gemini API key was not set!")

        genai.configure(api_key=gemini_key)
        model = genai.GenerativeModel(
            model_name=model_name,
            system_instruction=cls.SYSTEM_INSTRUCTION,
        )

        # Prepare the user prompt
        user_prompt = (
            f"{cls.USER_PROMPT}\n\nHere is the metadata of the transcription:\n\n{json.dumps(metadata, indent=2)}\n\n"
            f"Here is the transcription:\n\n{timestamped_transcription}"
        )

        result = model.generate_content(
            [user_prompt],
            generation_config=genai.GenerationConfig(
                response_mime_type="application/json", response_schema=cls.OUTPUT_SCHEMA
            ),
        )
        return result.text
