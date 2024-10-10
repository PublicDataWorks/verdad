import os
import boto3
from dotenv import load_dotenv
import json

import sentry_sdk
from processing_pipeline.supabase_utils import SupabaseClient
from processing_pipeline.stage_1 import __download_audio_file_from_s3, Stage1Executor

load_dotenv()

# Setup Sentry
sentry_sdk.init(dsn=os.getenv("SENTRY_DSN"))

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

if __name__ == "__main__":
    audio_file = supabase_client.get_audio_file_by_id("92c25040-3d6d-40e0-b6b9-eb6497cb2dcb")
    print(json.dumps(audio_file, indent=2))

    # Download the audio file
    local_file = __download_audio_file_from_s3(s3_client, R2_BUCKET_NAME, audio_file["file_path"])

    # Process the audio file
    print(f"Processing audio file: {local_file}")
    response = Stage1Executor.run(
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
    response = json.loads(response)
    print(json.dumps(response, indent=2))

    # Delete the downloaded audio file
    os.remove(local_file)
