import os
import boto3
from dotenv import load_dotenv

import sentry_sdk
from processing_pipeline.supabase_utils import SupabaseClient
from processing_pipeline.timestamped_transcription_generator import TimestampedTranscriptionGenerator

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
    # Download the audio file from R2
    audio_file = "radio_080377_20241124_172450.mp3"
    s3_client.download_file(R2_BUCKET_NAME, "radio_080377/radio_080377_20241124_172450.mp3", "radio_080377_20241124_172450.mp3")

    try:
        if os.path.exists(audio_file):
            result = TimestampedTranscriptionGenerator.run(audio_file, GEMINI_KEY, 10)
            print(result)
        else:
            print(f"File {audio_file} does not exist")
    finally:
        # Delete the local file
        os.remove(audio_file)
