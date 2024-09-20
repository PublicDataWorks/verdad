import hashlib
import os
import time
import boto3

from dotenv import load_dotenv
from prefect import flow, serve, task
from ffmpeg import FFmpeg
from botocore.exceptions import NoCredentialsError

from radiostations.dn_rtv import DnRtv
from radiostations.vov1 import Vov1

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
def capture_audio_stream(station, duration_seconds, audio_birate, audio_channels):
    try:
        station.setup_virtual_audio()
        station.start_browser()

        if station.is_audio_playing():
            print(f"Audio is properly set up and playing for {station.code}")
        else:
            raise Exception(f"Sink is not in RUNNING state for {station.code}")

        # Create the output filename using the timestamp and hash
        start_time = time.time()
        timestamp = time.strftime("%Y%m%d_%H%M%S", time.localtime(start_time))
        output_file = f"radio_{get_url_hash(station.url)}_{timestamp}.mp3"

        print(f"Start capturing audio from ${station.url} for {duration_seconds} seconds")
        FFmpeg().option("y").input(station.source_name, f="pulse", t=duration_seconds).output(
            output_file, ab=audio_birate, ac=audio_channels, acodec="libmp3lame"
        ).execute()

        return output_file

    except Exception as e:
        print(f"Failed to capture audio stream ${station.url}: {e}")
        return None
    finally:
        print("Stopping the stream and cleaning up...")
        station.stop()
        print("Cleanup finished")


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


@flow(name="Generic Audio Processing Pipeline")
def generic_audio_processing_pipeline(station_code, duration_seconds, audio_birate, audio_channels, repeat):
    # TODO
    # 1. Don't repeat the full flow, just repeat the recording part with ffmpeg. For now, the "repeat" doesn't work yet
    # 2. Split the capture_audio tasks into smaller tasks with retry mechanism
    # 3. Periodically check if the playback is still running or not, and restart it when neccessary (please also check for the volume to ensure its accuracy)
    # 4. Fix the problems in Prefect server logs
    # 5. Continue to write selenium script for other radio stations

    RADIO_STATIONS = {
        Vov1.code: Vov1,
        DnRtv.code: DnRtv,
    }
    # Reconstruct the radion station object based on the station code
    station = RADIO_STATIONS.get(station_code, lambda: None)()

    while True:
        audio_file = capture_audio_stream(station, duration_seconds, audio_birate, audio_channels)

        if audio_file:
            upload_to_r2_and_clean_up(station.url, audio_file)

        # Stop the flow if it should not be repeated
        if not repeat:
            break


def get_url_hash(url):
    # Hash the URL and get the last 6 characters
    return hashlib.sha256(url.encode()).hexdigest()[-6:]


if __name__ == "__main__":
    radio_stations = [Vov1(), DnRtv()]
    duration_seconds = 1800  # Default to 30 minutes
    audio_birate = 64000  # Default to 64kbps bitrate
    audio_channels = 1  # Default to single channel (mono audio)
    concurrency_limit = 100

    all_deployments = []
    for station in radio_stations:
        deployment = generic_audio_processing_pipeline.to_deployment(
            f"{station.code}",
            tags=[station.state],
            parameters=dict(
                station_code=station.code,
                duration_seconds=duration_seconds,
                repeat=True,
                audio_birate=audio_birate,
                audio_channels=audio_channels,
            ),
        )
        all_deployments.append(deployment)

    serve(*all_deployments, limit=concurrency_limit)
