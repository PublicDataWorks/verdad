import json
import os
import pathlib
from pydub import AudioSegment
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold

from processing_pipeline.constants import get_timestamped_transcription_generation_prompt

class TimestampedTranscriptionGenerator:

    USER_PROMPT = get_timestamped_transcription_generation_prompt()
    OUTPUT_SCHEMA = {
        "type": "object",
        "required": ["segments"],
        "properties": {
            "segments": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["segment", "transcription"],
                    "properties": {
                        "segment": {
                            "type": "integer",
                            "description": "The audio segment number"
                        },
                        "transcription": {
                            "type": "string",
                            "description": "The transcription of the audio segment"
                        }
                    }
                }
            }
        }
    }

    @classmethod
    def run(cls, audio_file, gemini_key):
        # Define the segment length in seconds
        segment_length = 10

        # Split the file into segments
        audio_segments = cls.split_file_into_segments(audio_file, segment_length * 1000)

        try:
            return cls.transcribe_segments(audio_segments, segment_length, gemini_key)
        finally:
            # Delete the segments
            for segment in audio_segments:
                os.remove(segment)


    @classmethod
    def transcribe_segments(cls, audio_segments, segment_length, gemini_key):
        if not gemini_key:
            raise ValueError("Google Gemini API key was not set!")

        if not audio_segments:
            raise ValueError("No audio segments provided!")

        genai.configure(api_key=gemini_key)
        model = genai.GenerativeModel(model_name="gemini-1.5-pro-002")

        segments = []
        for index, segment_path in enumerate(audio_segments):
            segments.extend([
                f"\n<Segment {index + 1}>\n",
                {
                    "mime_type": "audio/mp3",
                    "data": pathlib.Path(segment_path).read_bytes()
                },
                f"\n</Segment {index + 1}>\n\n",
            ])

        result = model.generate_content(
            [cls.USER_PROMPT] + segments,
            generation_config=genai.GenerationConfig(
                response_mime_type="application/json",
                response_schema=cls.OUTPUT_SCHEMA,
                max_output_tokens=8192
            ),
            safety_settings={
                HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
            },
        )
        segments = json.loads(result.text)["segments"]
        segment_transcriptions = [segment["transcription"] for segment in segments]

        return cls.build_timestamped_transcription(segment_transcriptions, segment_length)

    @classmethod
    def build_timestamped_transcription(cls, segment_transcriptions, segment_length):
        result = ""
        for i, transcription in enumerate(segment_transcriptions):
            # Convert the segment duration to minutes and seconds
            minutes = segment_length * i // 60
            seconds = segment_length * i % 60

            result += f"[{minutes:02}:{seconds:02}] {transcription}\n"

        return result

    @classmethod
    def split_file_into_segments(cls, file, segment_length):
        # Load the audio file
        audio = AudioSegment.from_mp3(file)
        segments = []

        for i in range(0, len(audio), segment_length):
            # Slice the audio segment
            subclip = audio[i:i + segment_length]

            # Export the subclip
            output_file = f"{file}_segment_{(i // segment_length) + 1}.mp3"
            subclip.export(output_file, format="mp3")

            segments.append(output_file)

        return segments
