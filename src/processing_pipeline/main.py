import os
from dotenv import load_dotenv
import sentry_sdk
import boto3
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


def main():
    # response = Stage1.run(
    #     gemini_key=GEMINI_KEY,
    #     audio_file="sample_audio.mp3",
    #     metadata={
    #         "radio_station_name": "The Salt",
    #         "radio_station_code": "WMUZ",
    #         "location": {"state": "New York", "city": "New York City"},
    #         "broadcast_date": "2023-01-01",
    #         "broadcast_time": "12:00:00",
    #         "day_of_week": "Sunday",
    #         "local_time_zone": "UTC",
    #     },
    # )
    # print(response)
    pass


if __name__ == "__main__":
    print("Hello from processing worker")
