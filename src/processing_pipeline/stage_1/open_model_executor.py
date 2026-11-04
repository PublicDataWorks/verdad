"""STAGE1_TRANSCRIPTION_METHOD=open_model: routing and formatting only; the models live in ``open_model_engines``.

Per the VER-448 eval: the language is voted over 30 s windows; Arabic goes to Cohere in 20 s chunks plus a CTC aligner,
the rest to Whisper with the voted language. The result has the same views as the Transcribe path.
"""

import re
import unicodedata
from collections import Counter
from itertools import pairwise
from typing import Protocol, Sequence

from processing_pipeline.stage_1.executors import GeminiTimestampTranscriptionGenerator
from processing_pipeline.stage_1.transcribe_executor import (
    EMPTY_TRANSCRIPT_MAX_SECONDS,
    GeminiTranscribeTimestampGenerator,
    TranscribeResult,
)

SAMPLE_RATE = 16000
VOTE_WINDOW_SECONDS = 30
ARABIC_CHUNK_SECONDS = 20
WHISPER_LABEL = "faster-whisper-large-v3"
ARABIC_LABEL = "cohere-transcribe-arabic+omniASR_CTC_1B_v2"


def ctc_min_frames(tokens: Sequence[int]) -> int:
    """Frames CTC forced alignment needs: one per token plus a blank between repeated tokens."""
    return len(tokens) + sum(a == b for a, b in pairwise(tokens))


class OpenModelEngines(Protocol):
    def load_audio(self, audio_file: str) -> Sequence[float]: ...

    def window_language(self, window: Sequence[float]) -> str | None:
        """Whisper's language code for the window, or None when it has too little speech to vote."""

    def whisper_words(self, audio: Sequence[float], language: str | None) -> list[dict]: ...

    def cohere_texts(self, chunks: list[Sequence[float]]) -> list[str]: ...

    def align(self, chunk: Sequence[float], words: list[str], offset: float) -> list[dict]: ...


def _nfkc(text: str) -> str:
    return unicodedata.normalize("NFKC", text).strip()


class OpenModelTranscriber:
    def __init__(self, engines: OpenModelEngines):
        self.engines = engines

    def transcribe(self, audio_file: str, segment_length: int = 20) -> TranscribeResult:
        audio = self.engines.load_audio(audio_file)
        duration_s = len(audio) / SAMPLE_RATE
        language = self.vote_language(audio)
        if language == "ar":
            words, model = self.arabic_words(audio), ARABIC_LABEL
        else:
            words, model = self.engines.whisper_words(audio, language), WHISPER_LABEL
        print(f"{model} ({language or 'no vote'}) returned {len(words)} timed words")

        words = [
            {"text": _nfkc(w["text"]), "start": round(w["start"], 3), "end": round(w["end"], 3), "speaker": None}
            for w in words
            if _nfkc(w["text"])
        ]
        if not words and duration_s > EMPTY_TRANSCRIPT_MAX_SECONDS:
            raise ValueError(f"{model} returned no words for {duration_s:.0f} s of audio")

        segments = GeminiTranscribeTimestampGenerator.bucket_words(words, round(duration_s * 1000), segment_length)
        return TranscribeResult(
            text=" ".join(w["text"] for w in words),
            windows={(n - 1) * segment_length: text for n, text in segments.items()},
            timestamped_transcription=GeminiTimestampTranscriptionGenerator.format_final_transcription(
                segments, segment_length
            ),
            words=words,
            duration_s=duration_s,
            model=model,
        )

    def vote_language(self, audio: Sequence[float]) -> str | None:
        step = VOTE_WINDOW_SECONDS * SAMPLE_RATE
        votes = Counter(self.engines.window_language(audio[i : i + step]) for i in range(0, len(audio), step))
        votes.pop(None, None)
        return votes.most_common(1)[0][0] if votes else None

    def arabic_words(self, audio: Sequence[float]) -> list[dict]:
        step = ARABIC_CHUNK_SECONDS * SAMPLE_RATE
        chunks = [audio[i : i + step] for i in range(0, len(audio) - SAMPLE_RATE + 1, step)]  # drops a tail under 1 s
        words = []
        for i, (chunk, text) in enumerate(zip(chunks, self.engines.cohere_texts(chunks), strict=True)):
            tokens = re.sub(r"[^\w\s]", " ", _nfkc(text)).split()
            if tokens:
                words += self.engines.align(chunk, tokens, i * ARABIC_CHUNK_SECONDS)
        return words
