import json
import os
import pathlib
from pydub import AudioSegment
from google import genai
from google.genai.types import (
    SafetySetting,
    HarmCategory,
    HarmBlockThreshold,
    Part,
    ThinkingConfig,
    GenerateContentConfig,
)
from processing_pipeline.constants import (
    GeminiModel,
    get_timestamped_transcription_generation_output_schema,
    get_timestamped_transcription_generation_prompt,
)


class TimestampedTranscriptionGenerator:

    SYSTEM_INSTRUCTION = (
        "You are a specialized language model designed to transcribe audio content in multiple languages."
    )
    USER_PROMPT = get_timestamped_transcription_generation_prompt()
    OUTPUT_SCHEMA = get_timestamped_transcription_generation_output_schema()

    @classmethod
    def run(cls, audio_file, gemini_key, segment_length):
        print("Splitting the file into 2 equal parts...")
        first_part, second_part = cls.split_file_into_two_parts(audio_file, segment_length)

        try:
            print("Splitting the first part into segments...")
            first_part_segments = cls.split_file_into_segments(first_part, segment_length * 1000)
            try:
                print("Transcribing the first part...")
                first = cls.transcribe_segments(first_part_segments, gemini_key)
            finally:
                print("Removing the first part segments...")
                for s in first_part_segments:
                    os.remove(s)

            print("Splitting the second part into segments...")
            second_part_segments = cls.split_file_into_segments(second_part, segment_length * 1000)
            try:
                print("Transcribing the second part...")
                second = cls.transcribe_segments(second_part_segments, gemini_key)
            finally:
                print("Removing the second part segments...")
                for s in second_part_segments:
                    os.remove(s)
        finally:
            print("Removing the two audio parts...")
            os.remove(first_part)
            os.remove(second_part)

        print("Combining segments from both parts...")
        segments = first + second
        print("Extracting the transcriptions from the segments...")
        segment_transcripts = [segment["transcript"] for segment in segments]

        print("Formatting the transcriptions into a timestamped transcription...")
        return cls.build_timestamped_transcription(segment_transcripts, segment_length)

    @classmethod
    def transcribe_segments(cls, audio_segments, gemini_key):
        if not gemini_key:
            raise ValueError("Google Gemini API key was not set!")

        if not audio_segments:
            raise ValueError("No audio segments provided!")

        client = genai.Client(api_key=gemini_key)

        segments = []
        for index, segment_path in enumerate(audio_segments):
            segments.extend(
                [
                    f"\n<Segment {index + 1}>\n",
                    Part.from_bytes(data=pathlib.Path(segment_path).read_bytes(), mime_type="audio/mp3"),
                    f"\n</Segment {index + 1}>\n\n",
                ]
            )

        result = client.models.generate_content(
            model=GeminiModel.GEMINI_FLASH_LATEST,
            contents=[cls.USER_PROMPT] + segments,
            config=GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=cls.OUTPUT_SCHEMA,
                system_instruction=cls.SYSTEM_INSTRUCTION,
                max_output_tokens=16384,
                thinking_config=ThinkingConfig(thinking_budget=1024),
                safety_settings=[
                    SafetySetting(
                        category=HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
                        threshold=HarmBlockThreshold.BLOCK_NONE,
                    ),
                    SafetySetting(
                        category=HarmCategory.HARM_CATEGORY_HATE_SPEECH,
                        threshold=HarmBlockThreshold.BLOCK_NONE,
                    ),
                    SafetySetting(
                        category=HarmCategory.HARM_CATEGORY_HARASSMENT,
                        threshold=HarmBlockThreshold.BLOCK_NONE,
                    ),
                    SafetySetting(
                        category=HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
                        threshold=HarmBlockThreshold.BLOCK_NONE,
                    ),
                ],
            ),
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
    def split_file_into_segments(cls, audio_file, segment_length_ms):
        audio = AudioSegment.from_mp3(audio_file)
        segments = []

        for i in range(0, len(audio), segment_length_ms):
            # Slice the audio segment
            subclip = audio[i : i + segment_length_ms]

            # Export the subclip
            output_file = f"{audio_file}_segment_{(i // segment_length_ms) + 1}.mp3"
            subclip.export(output_file, format="mp3")

            segments.append(output_file)

        del audio
        return segments

    @classmethod
    def split_file_into_two_parts(cls, file, segment_length):
        audio = AudioSegment.from_mp3(file)
        half_length = len(audio) // 2
        segment_length_ms = segment_length * 1000

        # Round down the half_length to the nearest multiple of segment_length_ms
        split_point = int((half_length // segment_length_ms) * segment_length_ms)
        print(f"Split point is at {split_point} milliseconds")

        first_part = audio[:split_point]
        second_part = audio[split_point:]

        # Export the parts
        first_part.export(f"{file}_part_1.mp3", format="mp3")
        second_part.export(f"{file}_part_2.mp3", format="mp3")

        # Release the memory
        del audio
        del first_part
        del second_part

        return f"{file}_part_1.mp3", f"{file}_part_2.mp3"
