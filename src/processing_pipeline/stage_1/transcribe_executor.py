"""Timestamped transcription with gemini-3.5-transcribe (STAGE1_TRANSCRIPTION_METHOD=transcribe).

One request per recording instead of 90 inline 20 s slices. Word timestamps come only from the interactions REST
endpoint (generate_content returns the text without them), so the audio goes up through the Files API and the
transcription request is a plain HTTP POST. The words are bucketed by start time into the same 20 s windows the
segments path produces, and the output is the exact ``[MM:SS] text`` format of
``GeminiTimestampTranscriptionGenerator.format_final_transcription``: one line per window from 00:00 to the end of
the audio, an empty window being ``[MM:SS] `` like an empty segment. Main detection, Stage 2 clipping and the
detection prompt see no difference.

``transcribe()`` returns every view of the one response (``TranscribeResult``): the plain transcript, the 20 s
windows, the ``[MM:SS]`` string and the timed words. ``run()`` returns only the ``[MM:SS]`` string, as before.
"""

import math
import os
import subprocess
import time
from dataclasses import dataclass, field
from http import HTTPStatus

import requests
from google import genai
from google.genai.types import UploadFileConfig
from pydub import AudioSegment

from processing_pipeline.gemini_retry import TRANSIENT_HTTP
from processing_pipeline.model_config import ModelName
from processing_pipeline.stage_1.executors import GeminiTimestampTranscriptionGenerator

INTERACTIONS_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"

# The API caps a request with timestamps at 30 minutes; recordings are exactly 1800 s, so trim a hair off those.
TRIM_ABOVE_SECONDS = 1799.5
TRIM_TO_SECONDS = 1799

# One 30 min recording took about 50 s in the October 2026 eval; leave room for a slow queue.
REQUEST_TIMEOUT_SECONDS = 900

# Waits between attempts on 429/5xx or a dropped connection, then the error propagates to the task's own retries.
RETRY_DELAYS = (30, 60, 120)

# Radio talk is never silent this long; no words beyond it means a broken response, not a quiet recording.
EMPTY_TRANSCRIPT_MAX_SECONDS = 300


class TranscribeAPIError(RuntimeError):
    def __init__(self, status_code: int | None, message: str):
        super().__init__(message)
        self.status_code = status_code


@dataclass
class TranscribeResult:
    """Every view of one Transcribe response; no view costs another model call.

    - ``text``: the plain transcript (the model's text parts; the words joined by spaces when there are none), the
      input to KB retrieval and initial detection.
    - ``windows``: ``{window start in seconds: text}`` at ``segment_length``, one entry per window of the audio.
    - ``timestamped_transcription``: the same windows as ``[MM:SS] text`` lines, the main-detection input.
    - ``words``: ``[{"text", "start", "end", "speaker"}]`` in seconds from the start of the recording; ``speaker``
      is None unless the response carries one.
    - ``duration_s``: the length of the recording that was passed in (before any trim for the request).
    """

    text: str
    windows: dict[int, str]
    timestamped_transcription: str
    words: list[dict] = field(default_factory=list)
    duration_s: float = 0.0

    def to_storage(self) -> dict:
        """The ``stage_1_llm_responses.timestamped_transcription`` value: the key Stage 2/3 read, plus the words."""
        return {"timestamped_transcription": self.timestamped_transcription, "words": self.words}


class GeminiTranscribeTimestampGenerator:
    @classmethod
    def run(
        cls,
        gemini_client: genai.Client,
        audio_file: str,
        model_name: ModelName,
        segment_length: int = 20,
        api_key: str | None = None,
    ) -> str:
        """The ``[MM:SS] text`` transcript only; see ``transcribe`` for the other views."""
        return cls.transcribe(gemini_client, audio_file, model_name, segment_length, api_key).timestamped_transcription

    @classmethod
    def transcribe(
        cls,
        gemini_client: genai.Client,
        audio_file: str,
        model_name: ModelName,
        segment_length: int = 20,
        api_key: str | None = None,
    ) -> TranscribeResult:
        api_key = api_key or os.getenv("GOOGLE_GEMINI_KEY")
        if not api_key:
            raise ValueError("GOOGLE_GEMINI_KEY is not set")

        duration_ms = len(AudioSegment.from_mp3(audio_file))
        print(f"Audio duration: {duration_ms / 1000:.1f} seconds")

        upload_path = cls.trim_audio(audio_file, TRIM_TO_SECONDS) if cls.needs_trim(duration_ms) else audio_file
        try:
            response = cls.transcribe_file(gemini_client, upload_path, model_name, api_key)
        finally:
            if upload_path != audio_file and os.path.exists(upload_path):
                os.remove(upload_path)

        words = cls.extract_timed_words(response)
        print(f"{model_name} returned {len(words)} timed words")
        if not words and duration_ms / 1000 > EMPTY_TRANSCRIPT_MAX_SECONDS:
            raise ValueError(f"{model_name} returned no words for {duration_ms / 1000:.0f} s of audio")
        segments = cls.bucket_words(words, duration_ms, segment_length)
        return TranscribeResult(
            text=cls.extract_text(response) or " ".join(w["text"] for w in words),
            windows={(n - 1) * segment_length: text for n, text in segments.items()},
            timestamped_transcription=GeminiTimestampTranscriptionGenerator.format_final_transcription(
                segments, segment_length
            ),
            words=words,
            duration_s=duration_ms / 1000,
        )

    @staticmethod
    def needs_trim(duration_ms: int) -> bool:
        return duration_ms / 1000 > TRIM_ABOVE_SECONDS

    @staticmethod
    def trim_audio(audio_file: str, seconds: int) -> str:
        """Copy the first ``seconds`` of the mp3 without re-encoding (what the eval harness sent)."""
        output_file = f"{audio_file}_trim.mp3"
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-i", audio_file, "-t", str(seconds), "-c", "copy", output_file],
            check=True,
        )
        print(f"Trimmed the audio to {seconds} s for the transcription request")
        return output_file

    @classmethod
    def transcribe_file(cls, gemini_client: genai.Client, audio_file: str, model_name: ModelName, api_key: str):
        uploaded_file = gemini_client.files.upload(file=audio_file, config=UploadFileConfig(mime_type="audio/mp3"))
        try:
            while uploaded_file.state.name == "PROCESSING":
                print("Processing the uploaded audio file...")
                time.sleep(1)
                uploaded_file = gemini_client.files.get(name=uploaded_file.name)
            if uploaded_file.state.name == "FAILED":
                raise ValueError(f"The Files API could not process {audio_file}")

            return cls.request_transcription(api_key, model_name, uploaded_file.uri)
        finally:
            gemini_client.files.delete(name=uploaded_file.name)

    @staticmethod
    def build_request_body(model_name: ModelName, file_uri: str) -> dict:
        model = str(model_name)
        return {
            "model": model if model.startswith("models/") else f"models/{model}",
            "input": [{"type": "audio", "uri": file_uri, "mime_type": "audio/mp3"}],
            "generation_config": {
                "transcription_config": {"mode": {"type": "verbatim", "timestamp_granularities": ["word"]}}
            },
        }

    @classmethod
    def request_transcription(cls, api_key: str, model_name: ModelName, file_uri: str) -> dict:
        body = cls.build_request_body(model_name, file_uri)
        headers = {"x-goog-api-key": api_key, "content-type": "application/json"}

        for delay in (*RETRY_DELAYS, None):
            try:
                response = requests.post(INTERACTIONS_URL, headers=headers, json=body, timeout=REQUEST_TIMEOUT_SECONDS)
            except (requests.ConnectionError, requests.Timeout) as e:
                error = TranscribeAPIError(None, f"{type(e).__name__} calling the interactions endpoint: {e}")
            else:
                if response.status_code == HTTPStatus.OK:
                    return response.json()
                error = TranscribeAPIError(
                    response.status_code,
                    f"{response.status_code} from the interactions endpoint: {response.text[:500]}",
                )
                if response.status_code not in TRANSIENT_HTTP:
                    raise error

            if delay is None:
                raise error
            print(f"{error} Retrying in {delay} s")
            time.sleep(delay)

    @staticmethod
    def parse_offset(value) -> float | None:
        """``"12.300s"`` -> 12.3; None when absent or unparseable."""
        if value is None:
            return None
        try:
            return float(str(value).strip().rstrip("s"))
        except ValueError:
            return None

    @classmethod
    def extract_words(cls, response: dict) -> list[dict]:
        """``[{"text", "start"}]`` from every ``word_info`` annotation, in response order."""
        return [{"text": w["text"], "start": w["start"]} for w in cls.extract_timed_words(response)]

    @classmethod
    def extract_timed_words(cls, response: dict) -> list[dict]:
        """``[{"text", "start", "end", "speaker"}]`` from every ``word_info`` annotation, in response order.

        An untimed word keeps its neighbour's start; a missing or inverted end becomes the word's start. Times are
        rounded to milliseconds (the API's precision) so the stored list stays small.
        """
        status = response.get("status")
        if status != "completed":
            raise ValueError(f"Transcription interaction ended with status {status!r}")

        words = []
        has_text = False
        previous_start = 0.0
        for content in cls._contents(response):
            if (content.get("text") or "").strip():
                has_text = True
            for annotation in content.get("annotations") or []:
                if annotation.get("type") != "word_info":
                    continue
                text = (annotation.get("text") or "").strip()
                if not text:
                    continue
                start = cls.parse_offset(annotation.get("start_offset"))
                if start is None:
                    start = previous_start  # keep an untimed word with its neighbour
                previous_start = start
                end = cls.parse_offset(annotation.get("end_offset"))
                if end is None or end < start:
                    end = start
                words.append(
                    {"text": text, "start": round(start, 3), "end": round(end, 3), "speaker": annotation.get("speaker")}
                )

        if has_text and not words:
            raise ValueError("The transcription came back without word timestamps")
        return words

    @classmethod
    def extract_text(cls, response: dict) -> str:
        """The model's text parts, each stripped, one per line; empty when it returned none."""
        parts = [(content.get("text") or "").strip() for content in cls._contents(response)]
        return "\n".join(part for part in parts if part)

    @staticmethod
    def _contents(response: dict):
        for step in response.get("steps") or []:
            yield from step.get("content") or []

    @staticmethod
    def bucket_words(words: list[dict], duration_ms: int, segment_length: int) -> dict[int, str]:
        """``{segment_number: text}`` for every window 1..ceil(duration / segment_length), like the segments path.

        A word is placed by its start time. Timestamps past the end of the audio (seen in the eval: up to 230 s past
        a 30 min file) go to the last window rather than inventing lines the recording does not have.
        """
        window_count = math.ceil(duration_ms / (segment_length * 1000))
        buckets: dict[int, list[str]] = {n: [] for n in range(1, window_count + 1)}
        if window_count == 0:
            return {}
        for word in words:
            index = int(max(word["start"], 0) // segment_length) + 1
            buckets[min(index, window_count)].append(word["text"])
        return {n: " ".join(texts) for n, texts in buckets.items()}
