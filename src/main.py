import os
import time
import hashlib
import boto3
import prefect
from prefect import flow, serve, task

from ffmpeg import FFmpeg
from dotenv import load_dotenv
from botocore.exceptions import NoCredentialsError

from utils import fetch_radio_stations

load_dotenv()

# Setup S3 Client
R2_ENDPOINT_URL = os.getenv("R2_ENDPOINT_URL")
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY")
R2_BUCKET_NAME = os.getenv("R2_BUCKET_NAME")
s3_client = boto3.client(
    "s3", endpoint_url=R2_ENDPOINT_URL, aws_access_key_id=R2_ACCESS_KEY_ID, aws_secret_access_key=R2_SECRET_ACCESS_KEY
)


@task(log_prints=True)
def capture_audio_stream(url, duration_seconds, audio_birate, audio_channels):
    try:
        # Create the output filename using the timestamp and hash
        start_time = time.time()
        timestamp = time.strftime("%Y%m%d_%H%M%S", time.localtime(start_time))
        output_file = f"radio_{get_url_hash(url)}_{timestamp}.mp3"

        # Use ffmpeg to capture audio
        print(f"Start capturing audio from ${url} for {duration_seconds} seconds")
        FFmpeg().option("y").input(url, t=duration_seconds).output(
            output_file, ab=audio_birate, ac=audio_channels, acodec="libmp3lame"
        ).execute()

        return output_file

    except Exception as e:
        print(f"Failed to capture audio stream ${url}: {e}")
        return None


@task(log_prints=True, retries=3)
def upload_to_r2_and_clean_up(url, file_path):
    object_name = os.path.basename(file_path)

    try:
        url_hash = get_url_hash(url)
        destination_path = f"radio_{url_hash}/{object_name}"
        s3_client.upload_file(file_path, R2_BUCKET_NAME, destination_path)
        print(f"File {file_path} uploaded to R2 as {destination_path}")
        os.remove(file_path)
    except NoCredentialsError:
        print("R2 Credentials was not set")
    except Exception as e:
        raise prefect.exceptions.RetryException(
            message="Error uploading the file {object_name} to R2, retrying..."
        ) from e


@flow(name="Audio Processing Pipeline")
def audio_processing_pipeline(url, duration_seconds, audio_birate, audio_channels, repeat):
    while True:
        audio_file = capture_audio_stream(url, duration_seconds, audio_birate, audio_channels)

        if audio_file:
            upload_to_r2_and_clean_up(url, audio_file)

        # Stop the flow if it should not be repeated
        if not repeat:
            break


def get_url_hash(url):
    # Hash the URL and get the last 6 characters
    return hashlib.sha256(url.encode()).hexdigest()[-6:]


if __name__ == "__main__":
    radio_stations = fetch_radio_stations()
    duration_seconds = 1800  # Default to 30 minutes
    audio_birate = 64000  # Default to 64kbps bitrate
    audio_channels = 1  # Default to single channel (mono audio)
    concurrency_limit = 100

    all_deployments = []
    for station in radio_stations:
        deployment = audio_processing_pipeline.to_deployment(
            f'{station["code"]}',
            tags=[station["state"]],
            parameters=dict(
                url=station["url"],
                duration_seconds=duration_seconds,
                repeat=True,
                audio_birate=audio_birate,
                audio_channels=audio_channels,
            ),
        )
        all_deployments.append(deployment)

    serve(*all_deployments, limit=concurrency_limit)
