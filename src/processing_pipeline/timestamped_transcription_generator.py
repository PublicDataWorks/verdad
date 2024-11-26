import json
import os
import pathlib
from pydub import AudioSegment
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
from constants import get_timestamped_transcription_generation_output_schema, get_timestamped_transcription_generation_prompt

class TimestampedTranscriptionGenerator:

    SYSTEM_INSTRUCTION = "You are a specialized language model designed to transcribe audio content in multiple languages, with a particular focus on Spanish and Arabic as spoken by immigrant communities in the USA."
    USER_PROMPT = get_timestamped_transcription_generation_prompt()
    OUTPUT_SCHEMA = get_timestamped_transcription_generation_output_schema()

    @classmethod
    def run(cls, audio_file, gemini_key, segment_length):
        # Split the file into 2 equal parts
        first_part, second_part = cls.split_file_into_two_parts(audio_file, segment_length)

        # Handle the first part
        first_part_segments = cls.split_file_into_segments(first_part, segment_length * 1000, audio_file)
        try:
            first =  cls.transcribe_segments(first_part_segments, gemini_key)
        finally:
            for s in first_part_segments:
                os.remove(s)

        # Handle the second part
        second_part_segments = cls.split_file_into_segments(second_part, segment_length * 1000, audio_file)
        try:
            second =  cls.transcribe_segments(second_part_segments, gemini_key)
        finally:
            for s in second_part_segments:
                os.remove(s)

        # Combine the two parts
        segments = first + second
        segment_transcriptions = [segment["transcription"] for segment in segments]
        return cls.build_timestamped_transcription(segment_transcriptions, segment_length)

    @classmethod
    def transcribe_segments(cls, audio_segments, gemini_key):
        if not gemini_key:
            raise ValueError("Google Gemini API key was not set!")

        if not audio_segments:
            raise ValueError("No audio segments provided!")

        genai.configure(api_key=gemini_key)
        model = genai.GenerativeModel(
            model_name="gemini-1.5-pro-002",
            system_instruction=cls.SYSTEM_INSTRUCTION
        )

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
        return json.loads(result.text)["segments"]

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
    def split_file_into_segments(cls, audio, segment_length, filename):
        segments = []

        for i in range(0, len(audio), segment_length):
            # Slice the audio segment
            subclip = audio[i:i + segment_length]

            # Export the subclip
            output_file = f"{filename}_segment_{(i // segment_length) + 1}.mp3"
            subclip.export(output_file, format="mp3")

            segments.append(output_file)

        return segments

    @classmethod
    def split_file_into_two_parts(cls, file, segment_length):
        audio = AudioSegment.from_mp3(file)
        half_length = len(audio) // 2

        # Convert half_length from milliseconds to seconds
        half_length_seconds = half_length / 1000

        # Round down to nearest multiple of segment_length seconds
        rounded_seconds = (half_length_seconds // segment_length) * segment_length

        # Convert back to milliseconds
        split_point = int(rounded_seconds * 1000)

        return audio[:split_point], audio[split_point:]
