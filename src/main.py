import json
import os
import subprocess
import time
import hashlib
from prefect import flow, task
import requests
import boto3

from ffmpeg import FFmpeg
from dotenv import load_dotenv
from openai import OpenAI
from botocore.exceptions import NoCredentialsError

load_dotenv()

# Setup Open AI Client
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Setup S3 Client
R2_ENDPOINT_URL = os.getenv("R2_ENDPOINT_URL")
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY")
R2_BUCKET_NAME = os.getenv("R2_BUCKET_NAME")
s3_client = boto3.client(
    "s3", endpoint_url=R2_ENDPOINT_URL, aws_access_key_id=R2_ACCESS_KEY_ID, aws_secret_access_key=R2_SECRET_ACCESS_KEY
)


@task(log_prints=True)
def capture_audio_stream(url, duration_seconds, output_file):
    try:
        response = requests.get(url, stream=True, timeout=20)
        if response.status_code != 200:
            print(f"Failed to connect to the audio stream ${url}. Status code: {response.status_code}")
            return None, None

        # Use ffmpeg to capture audio
        FFmpeg().option("y").input(url, t=duration_seconds).output(output_file).execute()

        # Extract metadata to a file
        metadata_file = save_metadata(output_file)
        return output_file, metadata_file

    except Exception as e:
        # TODO: Handle retry with Prefect
        print(f"Failed to capture audio stream ${url}: {e}")
        return None, None


def save_metadata(audio_file):
    try:
        # Construct the ffprobe command
        command = ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", audio_file]

        # Run the ffprobe command
        output = subprocess.check_output(command).decode("utf-8")

        # Parse the JSON output
        metadata = json.loads(output)
        metadata_file = audio_file.replace(".mp3", "-metadata.txt")

        # Save metadata to a text file
        with open(metadata_file, "w") as f:
            json.dump(metadata, f, indent=4)

        return metadata_file

    except Exception as e:
        print(f"Failed to extract metadata of the file ${audio_file}: {e}")
        return None


@task(log_prints=True)
def upload_files_to_r2(url_hash, timestamp, metadata_file, audio_file, transcription_file):
    # Upload metadata
    upload_to_r2_and_clean_up(url_hash, timestamp, metadata_file)

    # Upload audio file
    upload_to_r2_and_clean_up(url_hash, timestamp, audio_file)

    # Upload transcription file
    upload_to_r2_and_clean_up(url_hash, timestamp, transcription_file)


def upload_to_r2_and_clean_up(url_hash, timestamp, file_path):
    object_name = os.path.basename(file_path)

    try:
        destination_path = f"radio_{url_hash}/{timestamp}/{object_name}"
        s3_client.upload_file(file_path, R2_BUCKET_NAME, destination_path)
        print(f"File {file_path} uploaded to R2 as {destination_path}")
        os.remove(file_path)
    except NoCredentialsError:
        print("R2 Credentials not available")
    except Exception as e:
        print(f"Error uploading to R2: {e}")


@task(log_prints=True)
def transcribe_audio_file(audio_file):
    # TODO: Use "Prompt parameter" to improve the reliability of Whisper
    # TODO: Post-process the transcription using LLMs
    # See more: https://platform.openai.com/docs/guides/speech-to-text/improving-reliability

    try:
        transcription = client.audio.transcriptions.create(
            model="whisper-1", file=open(audio_file, "rb"), response_format="text"
        )
        transcription_file = audio_file.replace(".mp3", ".txt")
        with open(transcription_file, "w") as f:
            f.write(transcription)
        return transcription_file
    except Exception as e:
        print(f"Failed to transcribe audio: {e}")
        return None


@flow(name="Audio Processing Pipeline")
def audio_processing_pipeline(url, duration_seconds, repeat=False):
    while True:
        # Create the output filename using the timestamp and hash
        start_time = time.time()
        timestamp = time.strftime("%Y%m%d_%H%M%S", time.localtime(start_time))
        url_hash = hashlib.sha256(url.encode()).hexdigest()[-6:]  # Hash the URL and get the last 6 characters
        output_file = f"radio_{url_hash}_{timestamp}.mp3"

        audio_file, metadata_file = capture_audio_stream(url, duration_seconds, output_file)
        if audio_file:
            transcription_file = transcribe_audio_file(audio_file)

        upload_files_to_r2(url_hash, timestamp, metadata_file, audio_file, transcription_file)

        # Stop the flow if it should not be repeated
        if not repeat:
            break


if __name__ == "__main__":
    url = "https://securenetg.com/radio/8090/radio.aac"
    duration_seconds = 60  # Duration for each audio segment
    audio_processing_pipeline(url, duration_seconds, repeat=True)
