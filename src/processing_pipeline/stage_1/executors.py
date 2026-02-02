import json
import os
import pathlib
import time

from google import genai
from google.genai.types import (
    FinishReason,
    GenerateContentConfig,
    Part,
    ThinkingConfig,
)
from prefect.tasks import exponential_backoff
from pydub import AudioSegment

from processing_pipeline.constants import GeminiModel
from processing_pipeline.processing_utils import get_safety_settings
from utils import optional_task


class Stage1PreprocessTranscriptionExecutor:

    @classmethod
    def run(
        cls,
        gemini_client: genai.Client,
        audio_file: str,
        model_name: GeminiModel,
        prompt_version: dict,
    ):
        # Upload the audio file and wait for it to finish processing
        uploaded_file = gemini_client.files.upload(file=audio_file)

        while uploaded_file.state.name == "PROCESSING":
            print("Processing the uploaded audio file...")
            time.sleep(1)
            uploaded_file = gemini_client.files.get(name=uploaded_file.name)

        try:
            result = gemini_client.models.generate_content(
                model=model_name,
                contents=[prompt_version["user_prompt"], uploaded_file],
                config=GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=prompt_version["output_schema"],
                    max_output_tokens=16384,
                    thinking_config=ThinkingConfig(thinking_budget=1024),
                    safety_settings=get_safety_settings(),
                ),
            )

            if not result.parsed:
                finish_reason = result.candidates[0].finish_reason
                if finish_reason == FinishReason.MAX_TOKENS:
                    raise ValueError("The response from Gemini was too long and was cut off.")
                print(f"Response finish reason: {finish_reason}")
                raise ValueError("No response from Gemini.")

            return result.parsed
        finally:
            gemini_client.files.delete(name=uploaded_file.name)


class Stage1PreprocessDetectionExecutor:

    @classmethod
    def run(
        cls,
        gemini_client: genai.Client,
        model_name: GeminiModel,
        transcription: str,
        metadata: dict,
        prompt_version: dict,
    ):
        # Prepare the user prompt
        user_prompt = (
            f"{prompt_version['user_prompt']}\n\n"
            f"Here is the metadata of the transcription:\n\n{json.dumps(metadata, indent=2)}\n\n"
            f"Here is the transcription:\n\n{transcription}"
        )

        result = gemini_client.models.generate_content(
            model=model_name,
            contents=[user_prompt],
            config=GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=prompt_version["output_schema"],
                max_output_tokens=16384,
                system_instruction=prompt_version.get("system_instruction"),
                thinking_config=ThinkingConfig(thinking_budget=2048),
                safety_settings=get_safety_settings(),
            ),
        )

        if not result.parsed:
            finish_reason = result.candidates[0].finish_reason
            if finish_reason == FinishReason.MAX_TOKENS:
                raise ValueError("The response from Gemini was too long and was cut off.")
            print(f"Response finish reason: {finish_reason}")
            raise ValueError("No response from Gemini.")

        return result.parsed


class Stage1Executor:

    @classmethod
    def run(
        cls,
        gemini_client: genai.Client,
        model_name: GeminiModel,
        timestamped_transcription: str,
        metadata: dict,
        prompt_version: dict,
    ):
        # Prepare the user prompt
        user_prompt = (
            f"{prompt_version['user_prompt']}\n\n"
            f"Here is the metadata of the transcription:\n\n{json.dumps(metadata, indent=2)}\n\n"
            f"Here is the timestamped transcription:\n\n{timestamped_transcription}"
        )

        result = gemini_client.models.generate_content(
            model=model_name,
            contents=[user_prompt],
            config=GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=prompt_version["output_schema"],
                max_output_tokens=16384,
                system_instruction=prompt_version["system_instruction"],
                thinking_config=ThinkingConfig(thinking_budget=4096),
                safety_settings=get_safety_settings(),
            ),
        )

        if not result.parsed:
            finish_reason = result.candidates[0].finish_reason
            if finish_reason == FinishReason.MAX_TOKENS:
                raise ValueError("The response from Gemini was too long and was cut off.")
            print(f"Response finish reason: {finish_reason}")
            raise ValueError("No response from Gemini.")

        return result.parsed


class GeminiTimestampTranscriptionGenerator:

    @classmethod
    def run(
        cls,
        gemini_client: genai.Client,
        audio_file: str,
        model_name: GeminiModel,
        prompt_version: dict,
        segment_length: int = 20,
        batch_size: int = 30,
    ) -> str:
        # Split audio into segments
        segment_paths = cls.split_audio_into_segments(audio_file, segment_length * 1000)
        total_segments = len(segment_paths)
        print(f"Split audio into {total_segments} segments of {segment_length}s each")

        all_transcripts = {}  # segment_number -> transcript

        try:
            for batch_start in range(0, total_segments, batch_size):
                batch_end = min(batch_start + batch_size, total_segments)
                batch_paths = segment_paths[batch_start:batch_end]

                print(f"Processing batch: segments {batch_start + 1}-{batch_end} of {total_segments}")

                result = cls.transcribe_batch(
                    gemini_client,
                    batch_paths,
                    model_name,
                    prompt_version,
                )

                # Validate segment count
                returned_segments = result.get("segments", [])
                expected_count = len(batch_paths)
                actual_count = len(returned_segments)
                if actual_count != expected_count:
                    raise ValueError(
                        f"Segment count mismatch: expected {expected_count} segments, "
                        f"got {actual_count} (batch_start={batch_start})"
                    )

                for segment in returned_segments:
                    segment_num = segment["segment_number"]
                    if segment_num < 1 or segment_num > expected_count:
                        raise ValueError(
                            f"Invalid segment_number {segment_num}: expected range 1-{expected_count} "
                            f"(batch_start={batch_start})"
                        )
                    absolute_segment_num = batch_start + segment_num
                    all_transcripts[absolute_segment_num] = segment["transcript"]

                print(f"Batch complete: transcribed {actual_count} segments")
                time.sleep(2)

        finally:
            for segment_path in segment_paths:
                if os.path.exists(segment_path):
                    os.remove(segment_path)

        return cls.format_final_transcription(all_transcripts, segment_length)

    @classmethod
    @optional_task(log_prints=True, retries=3, retry_delay_seconds=exponential_backoff(backoff_factor=2))
    def transcribe_batch(
        cls,
        gemini_client: genai.Client,
        segment_paths: list,
        model_name: GeminiModel,
        prompt_version: dict,
    ):
        segments = []
        for i, segment_path in enumerate(segment_paths):
            segment_num = i + 1
            segments.extend(
                [
                    f"\n<Segment {segment_num}>\n",
                    Part.from_bytes(data=pathlib.Path(segment_path).read_bytes(), mime_type="audio/mp3"),
                    f"\n</Segment {segment_num}>\n\n",
                ]
            )

        thinking_budget = 128 if model_name == GeminiModel.GEMINI_2_5_PRO else 0

        result = gemini_client.models.generate_content(
            model=model_name,
            contents=[prompt_version["user_prompt"]] + segments,
            config=GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=prompt_version["output_schema"],
                system_instruction=prompt_version["system_instruction"],
                max_output_tokens=16384,
                thinking_config=ThinkingConfig(thinking_budget=thinking_budget),
                safety_settings=get_safety_settings(),
            ),
        )

        if not result.parsed:
            finish_reason = result.candidates[0].finish_reason if result.candidates else None
            if finish_reason == FinishReason.MAX_TOKENS:
                raise ValueError("The response from Gemini was too long and was cut off.")
            raise ValueError(f"No response from Gemini. Finish reason: {finish_reason}.")

        return result.parsed

    @classmethod
    def format_final_transcription(cls, transcripts: dict, segment_length: int) -> str:
        result = ""

        for segment_num in sorted(transcripts.keys()):
            transcript = transcripts[segment_num]

            total_seconds = (segment_num - 1) * segment_length
            minutes = total_seconds // 60
            seconds = total_seconds % 60

            result += f"[{minutes:02}:{seconds:02}] {transcript}\n"

        return result

    @classmethod
    def split_audio_into_segments(cls, audio_file: str, segment_length_ms: int) -> list:
        audio = AudioSegment.from_mp3(audio_file)
        segments = []

        audio_length_ms = len(audio)
        print(f"Audio duration: {audio_length_ms / 1000:.1f} seconds")

        for i in range(0, audio_length_ms, segment_length_ms):
            # Slice the audio segment
            subclip = audio[i : min(i + segment_length_ms, audio_length_ms)]

            # Export the subclip
            output_file = f"{audio_file}_segment_{(i // segment_length_ms) + 1}.mp3"
            subclip.export(output_file, format="mp3")

            segments.append(output_file)

        del audio
        return segments
