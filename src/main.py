from datetime import datetime
import os
import time
import hashlib
import boto3
from prefect import flow, serve, task
from prefect.task_runners import ConcurrentTaskRunner

from ffmpeg import FFmpeg
from dotenv import load_dotenv
from botocore.exceptions import NoCredentialsError
import sentry_sdk

from processing_pipeline.supabase_utils import SupabaseClient
from utils import fetch_radio_stations

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

# Setup Supabase client
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase_client = SupabaseClient(SUPABASE_URL, SUPABASE_KEY)


@task(log_prints=True)
def capture_audio_stream(station, duration_seconds, audio_birate, audio_channels):
    try:
        url = station["url"]

        # Create the output filename using the timestamp and hash
        start_time = time.time()
        timestamp = time.strftime("%Y%m%d_%H%M%S", time.localtime(start_time))
        output_file = f"radio_{get_url_hash(url)}_{timestamp}.mp3"

        # Use ffmpeg to capture audio
        print(f"Start capturing audio from ${url} for {duration_seconds} seconds")
        FFmpeg().option("y").input(url, t=duration_seconds).output(
            output_file, ab=audio_birate, ac=audio_channels, acodec="libmp3lame"
        ).execute()

        return get_metadata(output_file, station, start_time)

    except Exception as e:
        print(f"Failed to capture audio stream ${url}: {e}")
        print("Sleep for 15 seconds before returning")
        time.sleep(15)
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
        return destination_path
    except NoCredentialsError:
        print("R2 Credentials was not set")
        return None


@task(log_prints=True)
def get_metadata(file, station, start_time):
    file_size = os.path.getsize(file)
    return {
        "file_name": file,
        "radio_station_name": station["name"],
        "radio_station_code": station["code"],
        "location_state": station["state"],
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(start_time)),
        "recording_day_of_week": datetime.fromtimestamp(start_time).strftime("%A"),
        "file_size": file_size,
    }


@task(log_prints=True, retries=3)
def insert_recorded_audio_file_into_database(metadata, uploaded_path):
    supabase_client.insert_audio_file(
        radio_station_name=metadata["radio_station_name"],
        radio_station_code=metadata["radio_station_code"],
        location_state=metadata["location_state"],
        recorded_at=metadata["recorded_at"],
        recording_day_of_week=metadata["recording_day_of_week"],
        file_path=uploaded_path,
        file_size=metadata["file_size"],
    )


@flow(name="Audio Recording", log_prints=True, task_runner=ConcurrentTaskRunner)
def audio_processing_pipeline(url, duration_seconds, audio_birate, audio_channels, repeat):
    # Reconstruct the radio station from the URL
    station = reconstruct_radio_station(url)
    if not station:
        raise ValueError(f"Radio station not found for URL: {url}")

    while True:
        output = capture_audio_stream(station, duration_seconds, audio_birate, audio_channels)

        if output and output["file_name"]:
            uploaded_path = upload_to_r2_and_clean_up(station["url"], output["file_name"])

            if uploaded_path:
                insert_recorded_audio_file_into_database(output, uploaded_path)

        # Stop the flow if it should not be repeated
        if not repeat:
            break


def reconstruct_radio_station(url):
    radio_stations = fetch_radio_stations()
    for station in radio_stations:
        if station["url"] == url:
            return station
    return None


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
            tags=[station["state"], get_url_hash(station["url"])],
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
