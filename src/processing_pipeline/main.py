import json
import os
import time
from dotenv import load_dotenv
from prefect import flow, serve, task
from prefect.task_runners import ConcurrentTaskRunner
import sentry_sdk
import boto3
from stage_1 import Stage1
from supabase_utils import SupabaseClient

load_dotenv()

# Setup Sentry
sentry_sdk.init(dsn=os.getenv("SENTRY_DSN"))

# Setup S3 Client
R2_ENDPOINT_URL = os.getenv("R2_ENDPOINT_URL")
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY")
R2_BUCKET_NAME = os.getenv("R2_BUCKET_NAME")
s3_client = boto3.client(
    "s3", endpoint_url=R2_ENDPOINT_URL, aws_access_key_id=R2_ACCESS_KEY_ID, aws_secret_access_key=R2_SECRET_ACCESS_KEY
)

# Setup Gemini Key
GEMINI_KEY = os.getenv("GOOGLE_GEMINI_KEY")

# Setup Supabase client
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase_client = SupabaseClient(SUPABASE_URL, SUPABASE_KEY)


@task(log_prints=True, retries=3)
def fetch_a_new_audio_file_from_supabase():
    audio_file = None
    response = supabase_client.get_audio_files(status="New", limit=1)
    if response:
        audio_file = response[0]
        print("Found a new audio file:")
        print(json.dumps(audio_file, indent=2))
    else:
        print("No new audio files found")
    return audio_file


@task(log_prints=True, retries=3)
def download_audio_file_from_s3(file_path):
    file_name = os.path.basename(file_path)
    s3_client.download_file(R2_BUCKET_NAME, file_path, file_name)
    return file_name

@task(log_prints=True, retries=3)
def insert_response_into_stage_1_llm_responses_table_in_supabase(response_json, audio_file_id):
    supabase_client.insert_stage_1_llm_response(audio_file_id, response_json)

@task(log_prints=True)
def process_audio_file(audio_file, local_file):
    try:
        print(f"Processing audio file: {local_file}")
        supabase_client.set_audio_file_status(audio_file["id"], "Processing")

        response = Stage1.run(
            gemini_key=GEMINI_KEY,
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
        insert_response_into_stage_1_llm_responses_table_in_supabase(response_json, audio_file["id"])

        print(f"Processing completed for {local_file}")
        supabase_client.set_audio_file_status(audio_file["id"], "Processed")

    except Exception as e:
        print(f"Failed to process audio file {local_file}: {e}")
        supabase_client.set_audio_file_status(audio_file["id"], "Error", str(e))

@flow(name="Initial Disinformation Detection", log_prints=True, task_runner=ConcurrentTaskRunner)
def initial_disinformation_detection(repeat):
    # TODO: Retry failed audio files (Error)
    # TODO: Ensure there're no pending audio files (Processing)

    while True:
        audio_file = fetch_a_new_audio_file_from_supabase()
        if audio_file:
            local_file = download_audio_file_from_s3(audio_file["file_path"])

            # Process the audio file
            process_audio_file(audio_file, local_file)

            print(f"Delete the downloaded audio file: {local_file}")
            os.remove(local_file)

        # Stop the flow if it should not be repeated
        if not repeat:
            break

        print("Sleep for 5 seconds before the next iteration")
        time.sleep(5)


if __name__ == "__main__":
    process_group = os.environ.get("FLY_PROCESS_GROUP")
    match process_group:
        case "initial_disinformation_detection":
            deployment = initial_disinformation_detection.to_deployment(
                name="Initial Disinformation Detection",
                concurrency_limit=10,  # TODO: Each deployment run should be separated by 5 seconds
                parameters=dict(repeat=True),
            )
            serve(deployment)
        case "audio_clipping":
            pass
        case "in_depth_analysis":
            pass
        case _:
            raise ValueError(f"Invalid process group: {process_group}")
