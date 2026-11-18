import json
import os
import pathlib
import threading
import time

from google import genai
from google.genai import errors
from google.genai.types import (
    Content,
    CreateCachedContentConfig,
    FinishReason,
    GenerateContentConfig,
    Part,
)
from prefect.tasks import exponential_backoff
from pydub import AudioSegment

from processing_pipeline.model_config import ModelName, stage1_detection_cache, thinking_config
from processing_pipeline.processing_utils import get_safety_settings
from utils import optional_task

_DETECTION_PLACEHOLDERS = ("{kb_context}", "{metadata}", "{timestamped_transcription}")
_DETECTION_CACHE_TTL_S = 3600
_DETECTION_CACHE_RENEW_BEFORE_S = 300
# (model, system instruction, fixed head) -> (cache name or None after a failed create, monotonic time to rebuild)
_DETECTION_CACHES: dict[tuple, tuple[str | None, float]] = {}
_DETECTION_CACHE_LOCK = threading.Lock()


def _split_detection_prompt(template: str) -> tuple[str, str] | None:
    """(fixed head, per-recording tail), cut at the last '---' line before the first placeholder."""
    positions = [i for i in (template.find(p) for p in _DETECTION_PLACEHOLDERS) if i >= 0]
    cut = template.rfind("\n---\n", 0, min(positions)) if positions else -1
    return (template[:cut], template[cut:]) if cut > 0 else None


def _detection_cache(gemini_client: genai.Client, model_name: ModelName, prompt_version: dict) -> tuple[str, str] | None:
    """(cache name, tail template) when the fixed prompt part sits in a live explicit cache, else None."""
    parts = _split_detection_prompt(prompt_version["user_prompt"])
    if not parts:
        return None
    head, tail = parts
    key = (model_name, prompt_version["system_instruction"], head)
    with _DETECTION_CACHE_LOCK:
        name, rebuild_at = _DETECTION_CACHES.get(key, (None, 0.0))
        if time.monotonic() >= rebuild_at:
            try:
                name = gemini_client.caches.create(
                    model=model_name,
                    config=CreateCachedContentConfig(
                        system_instruction=prompt_version["system_instruction"],
                        contents=[Content(role="user", parts=[Part(text=head.format())])],
                        ttl=f"{_DETECTION_CACHE_TTL_S}s",
                    ),
                ).name
                print(f"Detection cache created: {name}")
            except Exception as e:
                name = None
                print(f"Detection cache not created ({type(e).__name__}: {e}); running uncached")
            rebuild_at = time.monotonic() + _DETECTION_CACHE_TTL_S - _DETECTION_CACHE_RENEW_BEFORE_S
            _DETECTION_CACHES[key] = (name, rebuild_at)
    return (name, tail) if name else None


def _stop_using_detection_cache(name: str):
    """Uncached until the usual rebuild time, so a failing cache is not rebuilt on every call."""
    with _DETECTION_CACHE_LOCK:
        for key, (cached_name, rebuild_at) in _DETECTION_CACHES.items():
            if cached_name == name:
                _DETECTION_CACHES[key] = (None, rebuild_at)


class Stage1PreprocessTranscriptionExecutor:

    @classmethod
    def run(
        cls,
        gemini_client: genai.Client,
        audio_file: str,
        model_name: ModelName,
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
                    thinking_config=thinking_config(model_name, budget=1024),
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
        model_name: ModelName,
        transcription: str,
        metadata: dict,
        prompt_version: dict,
        kb_context: str | None,
    ):
        user_prompt = prompt_version["user_prompt"].format(
            kb_context=kb_context,
            metadata=json.dumps(metadata, indent=2),
            transcription=transcription,
        )

        result = gemini_client.models.generate_content(
            model=model_name,
            contents=[user_prompt],
            config=GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=prompt_version["output_schema"],
                max_output_tokens=16384,
                system_instruction=prompt_version.get("system_instruction"),
                thinking_config=thinking_config(model_name, budget=2048),
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
        model_name: ModelName,
        timestamped_transcription: str,
        metadata: dict,
        prompt_version: dict,
        kb_context: str | None = None,
    ):
        values = dict(
            kb_context=kb_context,
            metadata=json.dumps(metadata, indent=2),
            timestamped_transcription=timestamped_transcription,
        )

        def generate(template: str, **prefix):
            return gemini_client.models.generate_content(
                model=model_name,
                contents=[template.format(**values)],
                config=GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=prompt_version["output_schema"],
                    max_output_tokens=16384,
                    thinking_config=thinking_config(model_name, budget=4096, level="low"),
                    safety_settings=get_safety_settings(),
                    **prefix,
                ),
            )

        result = None
        cached = _detection_cache(gemini_client, model_name, prompt_version) if stage1_detection_cache() else None
        if cached:
            try:
                result = generate(cached[1], cached_content=cached[0])
            except errors.APIError as e:
                print(f"Detection call on the cache failed ({type(e).__name__}: {e}); running uncached")
                _stop_using_detection_cache(cached[0])
        if result is None:
            result = generate(prompt_version["user_prompt"], system_instruction=prompt_version["system_instruction"])

        usage = result.usage_metadata
        prompt_tokens = getattr(usage, "prompt_token_count", None) or 0
        cached_tokens = getattr(usage, "cached_content_token_count", None) or 0
        print(f"Detection token usage: prompt={prompt_tokens} cached={cached_tokens}")

        if not result.parsed:
            if not result.candidates:
                block_reason = result.prompt_feedback.block_reason if result.prompt_feedback else None
                raise ValueError(f"Gemini returned no candidates. Block reason: {block_reason}.")
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
        model_name: ModelName,
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
        model_name: ModelName,
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

        result = gemini_client.models.generate_content(
            model=model_name,
            contents=[prompt_version["user_prompt"]] + segments,
            config=GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=prompt_version["output_schema"],
                system_instruction=prompt_version["system_instruction"],
                max_output_tokens=16384,
                # budget 0: no thinking on Flash, the 128 minimum on 2.5 Pro, "minimal" on 3.x
                thinking_config=thinking_config(model_name, budget=0),
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
