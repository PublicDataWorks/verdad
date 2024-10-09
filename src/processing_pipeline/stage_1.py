import os
import time
import google.generativeai as genai
import json
import boto3
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
    file_name = os.path.basename(file_path)
    s3_client.download_file(r2_bucket_name, file_path, file_name)
    return file_name

@task(log_prints=True, retries=3)
def insert_response_into_stage_1_llm_responses_table_in_supabase(supabase_client, response_json, audio_file_id):
    supabase_client.insert_stage_1_llm_response(audio_file_id, response_json)

@task(log_prints=True)
def process_audio_file(supabase_client, audio_file, local_file, gemini_key):
    try:
        print(f"Processing audio file: {local_file}")
        response = Stage1Executor.run(
            gemini_key=gemini_key,
            audio_file=local_file,
            metadata={
                "radio_station_name": audio_file["radio_station_name"],
                "radio_station_code": audio_file["radio_station_code"],
                "location": {"state": audio_file["location_state"], "city": audio_file["location_city"]},
                "recorded_at": audio_file["recorded_at"],
                "recording_day_of_week": audio_file["recording_day_of_week"],
                "time_zone": "UTC",
            },
        )

        # Check if the response is a valid JSON
        response_json = json.loads(response)
        print(f"Response: ======================================\n{json.dumps(response, indent=2)}\n================================================")

        # Insert the response into the stage_1_llm_responses table in Supabase
        insert_response_into_stage_1_llm_responses_table_in_supabase(supabase_client, response_json, audio_file["id"])

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
        aws_secret_access_key=os.getenv("R2_SECRET_ACCESS_KEY")
    )

    # Setup Gemini Key
    GEMINI_KEY = os.getenv("GOOGLE_GEMINI_KEY")

    # Setup Supabase client
    supabase_client = SupabaseClient(
        supabase_url=os.getenv("SUPABASE_URL"),
        supabase_key=os.getenv("SUPABASE_KEY")
    )

    while True:
        audio_file = fetch_a_new_audio_file_from_supabase(supabase_client) # TODO: Retry failed audio files (Error)
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

        print("Sleep for 5 seconds before the next iteration")
        time.sleep(5)

class Stage1Executor:

    MODEL = "gemini-1.5-flash-002"
    SYSTEM_INSTRUCTION = get_system_instruction_for_stage_1()
    USER_PROMPT = get_user_prompt_for_stage_1()
    OUTPUT_SCHEMA = get_output_schema_for_stage_1()

    @classmethod
    def run(cls, gemini_key, audio_file, metadata):
        if not gemini_key:
            raise ValueError("Google Gemini API key was not set!")

        genai.configure(api_key=gemini_key)
        model = genai.GenerativeModel(
            model_name=cls.MODEL,
            system_instruction=cls.SYSTEM_INSTRUCTION,
        )

        # Upload the audio file and wait for it to finish processing
        audio_file = genai.upload_file(audio_file)
        while audio_file.state.name == "PROCESSING":
            print("Processing the uploaded audio file...")
            time.sleep(1)
            audio_file = genai.get_file(audio_file.name)

        # Prepare the user prompt
        user_prompt = (
            f"{cls.USER_PROMPT}\nHere is the metadata of the attached audio clip:\n{json.dumps(metadata, indent=2)}"
        )

        try:
            result = model.generate_content(
                [audio_file, user_prompt],
                generation_config=genai.GenerationConfig(
                    response_mime_type="application/json", response_schema=cls.OUTPUT_SCHEMA
                ),
            )
            return result.text
        finally:
            audio_file.delete()
