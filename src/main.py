import os
import time
import hashlib
import requests
import boto3
from prefect import flow, serve, task

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
def capture_audio_stream(url, duration_seconds):
    try:
        # Create the output filename using the timestamp and hash
        start_time = time.time()
        timestamp = time.strftime("%Y%m%d_%H%M%S", time.localtime(start_time))
        output_file = f"radio_{get_url_hash(url)}_{timestamp}.mp3"

        response = requests.get(url, stream=True, timeout=20)
        if response.status_code != 200:
            print(f"Failed to connect to the audio stream ${url}. Status code: {response.status_code}")
            return None

        # Use ffmpeg to capture audio
        FFmpeg().option("y").input(url, t=duration_seconds).output(output_file).execute()

        return output_file

    except Exception as e:
        # TODO: Handle retry with Prefect
        print(f"Failed to capture audio stream ${url}: {e}")
        return None


@task(log_prints=True)
def upload_files_to_r2(url, audio_file, transcription_file):
    upload_to_r2_and_clean_up(url, audio_file)
    upload_to_r2_and_clean_up(url, transcription_file)


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
def audio_processing_pipeline(url, duration_seconds, repeat):
    while True:
        audio_file = capture_audio_stream(url, duration_seconds)
        if audio_file:
            transcription_file = transcribe_audio_file(audio_file)

        upload_files_to_r2(url, audio_file, transcription_file)

        # Stop the flow if it should not be repeated
        if not repeat:
            break


def get_url_hash(url):
    # Hash the URL and get the last 6 characters
    return hashlib.sha256(url.encode()).hexdigest()[-6:]


if __name__ == "__main__":
    radio_stations = [
        {"code": "WLEL-FM 94.3 MHz", "url": "https://securenetg.com/radio/8090/radio.aac", "state": "Georgia"},
        {"code": "WPHE-AM 690 kHz", "url": "https://sp.unoredcdn.net/8124/stream", "state": "Pennsylvania"},
        {"code": "WLCH-FM 91.3 MHz", "url": "http://streaming.live365.com/a37354", "state": "Pennsylvania"},
        {"code": "WSDS-AM 1480 kHz", "url": "https://s2.mexside.net/6022/stream", "state": "Michigan"},
        {"code": "WOAP-AM 1080 kHz", "url": "http://sparktheo.com:8000/lapoderosa", "state": "Michigan"},
        {"code": "WDTW-AM 1310 kHz", "url": "http://sh2.radioonlinehd.com:8050/stream", "state": "Michigan"},
        {"code": "KYAR-FM 98.3 MHz", "url": "http://red-c.miriamtech.net:8000/KYAR", "state": "Texas"},
        {"code": "KBNL-FM 89.9 MHz", "url": "http://wrn.streamguys1.com/kbnl", "state": "Texas"},
        {"code": "KBIC-FM 105.7 MHz", "url": "http://shout2.brnstream.com:8006/;", "state": "Texas"},
        {"code": "KABA-FM 90.3 MHz", "url": "https://radio.aleluya.cloud/radio/8000/stream", "state": "Texas"},
        {"code": "WAXY-AM 790 kHz", "url": "http://stream.abacast.net/direct/audacy-waxyamaac-imc", "state": "Florida"},
        {"code": "WLAZ-FM 89.1 MHz", "url": "https://sp.unoredcdn.net/8018/stream", "state": "Florida, Orlando"},
        {
            "code": "KENO-AM 1460 kHz",
            "url": "https://23023.live.streamtheworld.com/KENOAMAAC_SC",
            "state": "Nevada",
        },
        {"code": "KNNR-AM 1400 kHz", "url": "https://ice42.securenetsystems.net/KNNR", "state": "Nevada"},
        {
            "code": "KCKO-FM 107.9 MHz",
            "url": "https://s5.mexside.net:8000/stream?type=http&nocache=3",
            "state": "Arizona",
        },
        {"code": "KZLZ-FM 105.3 MHz", "url": "https://ice42.securenetsystems.net/KZLZ", "state": "Arizona"},
        {
            "code": "KCMT-FM 92.1 MHz",
            "url": "https://23023.live.streamtheworld.com/KCMTFMAAC_SC",
            "state": "Arizona",
        },
        {"code": "KRMC-FM 91.7 MHz", "url": "http://wrn.streamguys1.com/krmc", "state": "Arizona"},
        {"code": "KNOG-FM 91.7 MHz", "url": "http://wrn.streamguys1.com/knog", "state": "Arizona"},
        {"code": "KWST-AM 1430 kHz", "url": "https://s1.voscast.com:10601/xstream", "state": "Arizona"},
    ]
    duration_seconds = 300

    all_deployments = []
    for station in radio_stations:
        deployment = audio_processing_pipeline.to_deployment(
            f'{station["code"]}',
            tags=[station["state"]],
            work_pool_name="local",
            parameters=dict(url=station["url"], duration_seconds=duration_seconds, repeat=False),
        )
        all_deployments.append(deployment)

    serve(*all_deployments)
