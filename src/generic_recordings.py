import hashlib
import os
import time
import boto3

from dotenv import load_dotenv
from prefect import flow, serve, task
from prefect.task_runners import ConcurrentTaskRunner
from ffmpeg import FFmpeg
from botocore.exceptions import NoCredentialsError
import psutil
import sentry_sdk

from radiostations.khot import Khot
from radiostations.kisf import Kisf
from radiostations.krgt import Krgt

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


@task(log_prints=True)
def capture_audio_stream(station, duration_seconds, audio_birate, audio_channels):
    try:
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


@flow(name="Generic Audio Processing Pipeline", log_prints=True, task_runner=ConcurrentTaskRunner)
def generic_audio_processing_pipeline(station_code, duration_seconds, audio_birate, audio_channels, repeat):
    RADIO_STATIONS = {
        Khot.code: Khot,
        Kisf.code: Kisf,
        Krgt.code: Krgt,
    }
    # Reconstruct the radion station object based on the station code
    station = RADIO_STATIONS.get(station_code, lambda: None)()

    station.setup_virtual_audio()
    station.start_browser()

    while True:
        # Check current memory usage
        memory_usage = psutil.virtual_memory().percent
        print(f"Current memory usage: {memory_usage}%")

        # If memory usage is above 95%, restart the browser
        if memory_usage > 95:
            print("Memory usage is high. Restarting browser...")
            station.stop(unload_modules=False)
            time.sleep(5)  # Wait for browser to fully close
            station.start_browser()
            print(f"Current memory usage: {psutil.virtual_memory().percent}%")

        if not station.is_audio_playing():
            station.start_playing()

        audio_file = capture_audio_stream(station, duration_seconds, audio_birate, audio_channels)

        if audio_file:
            upload_to_r2_and_clean_up(station.url, audio_file)

        # Stop the flow if it should not be repeated
        if not repeat:
            break

    print("Stopping the radio station and cleaning up...")
    station.stop()
    print("Cleanup finished")


def get_url_hash(url):
    # Hash the URL and get the last 6 characters
    return hashlib.sha256(url.encode()).hexdigest()[-6:]


if __name__ == "__main__":
    process_group = os.environ.get("FLY_PROCESS_GROUP")
    print(f"======== Starting {process_group} ========")

    match process_group:
        case "radio_khot":
            station = Khot()
        case "radio_kisf":
            station = Kisf()
        case "radio_krgt":
            station = Krgt()
        case _:
            raise Exception("Invalid process group")

    duration_seconds = 1800  # Default to 30 minutes
    audio_birate = 64000  # Default to 64kbps bitrate
    audio_channels = 1  # Default to single channel (mono audio)

    deployment = generic_audio_processing_pipeline.to_deployment(
        f"{station.code}",
        tags=[station.state, get_url_hash(station.url), "Generic"],
        parameters=dict(
            station_code=station.code,
            duration_seconds=duration_seconds,
            repeat=True,
            audio_birate=audio_birate,
            audio_channels=audio_channels,
        ),
    )
    serve(deployment)
