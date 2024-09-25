import os
import time
import hashlib
import prefect
import boto3
from prefect import flow, serve, task

from ffmpeg import FFmpeg
from dotenv import load_dotenv
from openai import OpenAI
from botocore.exceptions import NoCredentialsError

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


@task(log_prints=True)
def transcribe_audio_file(audio_file):
    # TODO: Use "Prompt parameter" to improve the reliability of Whisper
    # TODO: Post-process the transcription using LLMs
    # See more: https://platform.openai.com/docs/guides/speech-to-text/improving-reliability

    if not os.getenv("OPENAI_API_KEY"):
        print("Skipped audio transcription because open_ai key was not set!")
        return None

    # Setup Open AI Client
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

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
def audio_processing_pipeline(url, duration_seconds, audio_birate, audio_channels, repeat):
    while True:
        audio_file = capture_audio_stream(url, duration_seconds, audio_birate, audio_channels)
        transcription_file = None

        if audio_file:
            transcription_file = transcribe_audio_file(audio_file)

        if audio_file:
            upload_to_r2_and_clean_up(url, audio_file)
        if transcription_file:
            upload_to_r2_and_clean_up(url, transcription_file)

        # Stop the flow if it should not be repeated
        if not repeat:
            break


def get_url_hash(url):
    # Hash the URL and get the last 6 characters
    return hashlib.sha256(url.encode()).hexdigest()[-6:]


def fetch_radio_stations():
    return [
        {
            "code": "WLEL-FM 94.3 MHz",
            "url": "https://securenetg.com/radio/8090/radio.aac",
            "state": "Georgia",
            "tags": [],
        },
        {
            "code": "WPHE-AM 690 kHz",
            "url": "https://sp.unoredcdn.net/8124/stream",
            "state": "Pennsylvania",
            "tags": [],
        },
        {
            "code": "WLCH-FM 91.3 MHz",
            "url": "http://streaming.live365.com/a37354",
            "state": "Pennsylvania",
            "tags": [],
        },
        {
            "code": "WSDS-AM 1480 kHz",
            "url": "https://s2.mexside.net/6022/stream",
            "state": "Michigan",
            "tags": [],
        },
        {
            "code": "WOAP-AM 1080 kHz",
            "url": "http://sparktheo.com:8000/lapoderosa",
            "state": "Michigan",
            "tags": [],
        },
        {
            "code": "WDTW-AM 1310 kHz",
            "url": "http://sh2.radioonlinehd.com:8050/stream",
            "state": "Michigan",
            "tags": [],
        },
        {
            "code": "KYAR-FM 98.3 MHz",
            "url": "http://red-c.miriamtech.net:8000/KYAR",
            "state": "Texas",
            "tags": [],
        },
        {
            "code": "KBNL-FM 89.9 MHz",
            "url": "http://wrn.streamguys1.com/kbnl",
            "state": "Texas",
            "tags": [],
        },
        {
            "code": "KBIC-FM 105.7 MHz",
            "url": "http://shout2.brnstream.com:8006/;",
            "state": "Texas",
            "tags": [],
        },
        {
            "code": "KABA-FM 90.3 MHz",
            "url": "https://radio.aleluya.cloud/radio/8000/stream",
            "state": "Texas",
            "tags": [],
        },
        {
            "code": "WAXY-AM 790 kHz",
            "url": "http://stream.abacast.net/direct/audacy-waxyamaac-imc",
            "state": "Florida",
            "tags": [],
        },
        {
            "code": "WLAZ-FM 89.1 MHz",
            "url": "https://sp.unoredcdn.net/8018/stream",
            "state": "Florida, Orlando",
            "tags": [],
        },
        {
            "code": "KENO-AM 1460 kHz",
            "url": "https://23023.live.streamtheworld.com/KENOAMAAC_SC",
            "state": "Nevada",
            "tags": [],
        },
        {
            "code": "KNNR-AM 1400 kHz",
            "url": "https://ice42.securenetsystems.net/KNNR",
            "state": "Nevada",
            "tags": [],
        },
        {
            "code": "KCKO-FM 107.9 MHz",
            "url": "https://s5.mexside.net:8000/stream?type=http&nocache=3",
            "state": "Arizona",
            "tags": [],
        },
        {
            "code": "KZLZ-FM 105.3 MHz",
            "url": "https://ice42.securenetsystems.net/KZLZ",
            "state": "Arizona",
            "tags": [],
        },
        {
            "code": "KCMT-FM 92.1 MHz",
            "url": "https://23023.live.streamtheworld.com/KCMTFMAAC_SC",
            "state": "Arizona",
            "tags": [],
        },
        {
            "code": "KRMC-FM 91.7 MHz",
            "url": "http://wrn.streamguys1.com/krmc",
            "state": "Arizona",
            "tags": [],
        },
        {
            "code": "KNOG-FM 91.7 MHz",
            "url": "http://wrn.streamguys1.com/knog",
            "state": "Arizona",
            "tags": [],
        },
        {
            "code": "KWST-AM 1430 kHz",
            "url": "https://s1.voscast.com:10601/xstream",
            "state": "Arizona",
            "tags": [],
        },
        {
            "code": "WLMV-AM 1480 kHz",
            "url": "https://14223.live.streamtheworld.com/WLMVAMAAC_SC",
            "state": "Wisconsin",
            "tags": [],
        },
        # ===============================================================
        # iHeart Radio Stations
        # ===============================================================
        {
            "code": "K229DB-FM 93.7 MHz",
            "url": "http://stream.revma.ihrhls.com/zc53/hls.m3u8",
            "state": "Arizona",
            "tags": [],
        },
        {
            "code": "KFUE-FM 106.7 MHz",
            "url": "http://17793.live.streamtheworld.com:80/KFUEFMAAC_SC",
            "state": "Arizona",
            "tags": [],
        },
        {
            "code": "KISF-FM 103.5 MHz",
            "url": "http://lmn.streamguys1.com/kisffm/playlist.m3u8?key=a1e751202157c8d037a4f453698087f605c937356359a6774ea3fcd2e53d04e4&aw_0_1st.playerId=iheart",
            "state": "Nevada",
            "tags": [],
        },
        {
            "code": "KMMA-FM 97.1 MHz",
            "url": "http://stream.revma.ihrhls.com/zc69/hls.m3u8",
            "state": "Arizona",
            "tags": [],
        },
        {
            "code": "KRGT-FM 99.3 MHz",
            "url": "http://lmn.streamguys1.com/krgtfm/playlist.m3u8?key=a1e751202157c8d037a4f453698087f605c937356359a6774ea3fcd2e53d04e4&aw_0_1st.playerId=iheart",
            "state": "Nevada",
            "tags": [],
        },
        {
            "code": "RUMBA 4451",
            "url": "http://stream.revma.ihrhls.com/zc4451/hls.m3u8",
            "state": "Arizona",
            "tags": [],
        },
        {
            "code": "WBZW-FM 96.7 MHz",
            "url": "http://stream.revma.ihrhls.com/zc9205/hls.m3u8",
            "state": "Georgia",
            "tags": [],
        },
        {
            "code": "WBZY-FM 105.7 MHz",
            "url": "http://stream.revma.ihrhls.com/zc749/hls.m3u8",
            "state": "Georgia",
            "tags": [],
        },
        {
            "code": "WRUM-FM HD2 97.1 MHz",
            "url": "http://stream.revma.ihrhls.com/zc7155/hls.m3u8",
            "state": "Florida, Orlando",
            "tags": [],
        },
        {
            "code": "WRUM-FM 100.3 MHz",
            "url": "http://stream.revma.ihrhls.com/zc605/hls.m3u8",
            "state": "Florida, Orlando",
            "tags": [],
        },
        {
            "code": "WUMR-FM 106.1 MHz",
            "url": "http://stream.revma.ihrhls.com/zc2001/hls.m3u8",
            "state": "Pennsylvania",
            "tags": [],
        },
        {
            "code": "WZTU-FM 94.9 MHz",
            "url": "http://stream.revma.ihrhls.com/zc577/hls.m3u8",
            "state": "Florida",
            "tags": [],
        },
    ]


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
            tags=[station["state"], *station["tags"]],
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
