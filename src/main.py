import json
import os
import subprocess
import time
import hashlib
import requests

from ffmpeg import FFmpeg
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def capture_audio_stream(url, duration_seconds):
    response = requests.get(url, stream=True, timeout=20)
    if response.status_code != 200:
        print(f"Failed to connect to the audio stream. Status code: {response.status_code}")
        return

    # Create the output filename using the timestamp and hash
    start_time = time.time()
    timestamp = time.strftime("%Y%m%d_%H%M%S", time.localtime(start_time))
    url_hash = hashlib.sha256(url.encode()).hexdigest()[-6:]  # Hash the URL and get the last 6 characters
    output_file = f"radio_{url_hash}_{timestamp}.mp3"

    # Use ffmpeg to capture audio
    FFmpeg().option("y").input(url, t=duration_seconds).output(output_file).execute()

    # Extract metadata and save it
    save_metadata(output_file)

    yield output_file


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

    except Exception as e:
        print(f"Failed to extract metadata: {e}")


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


def translate_audio_file(audio_file):
    # TODO: Use "Prompt parameter" to improve the reliability of Whisper
    # TODO: Post-process the translation using LLMs
    # See more: https://platform.openai.com/docs/guides/speech-to-text/improving-reliability

    try:
        translation = client.audio.translations.create(
            model="whisper-1", file=open(audio_file, "rb"), response_format="text"
        )
        translation_file = audio_file.replace(".mp3", ".english.txt")
        with open(translation_file, "w") as f:
            f.write(translation)
        return translation_file
    except Exception as e:
        print(f"Failed to translate audio: {e}")
        return None


def audio_processing_pipeline(url, duration_seconds):
    for audio_file in capture_audio_stream(url, duration_seconds):
        # TODO: Execute transcription and translation in parallel
        # Is it possible to accomplish both tasks with one OpenAI call?
        transcription_file = transcribe_audio_file(audio_file)
        translation_file = translate_audio_file(audio_file)
        yield transcription_file, translation_file


if __name__ == "__main__":
    url = "https://securenetg.com/radio/8090/radio.aac"
    duration_seconds = 15  # Duration for each audio segment

    for transcription_file, translation_file in audio_processing_pipeline(url, duration_seconds):
        print(f"Transcription: {transcription_file}")
        print(f"Translation: {translation_file}")
