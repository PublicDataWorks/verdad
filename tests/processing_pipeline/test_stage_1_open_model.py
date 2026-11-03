"""STAGE1_TRANSCRIPTION_METHOD=open_model: language vote, then Whisper or Cohere + aligner -> TranscribeResult."""

import pytest

from processing_pipeline.stage_1.open_model_executor import (
    ARABIC_LABEL,
    SAMPLE_RATE,
    WHISPER_LABEL,
    OpenModelTranscriber,
)


def seconds(n):
    return range(int(n * SAMPLE_RATE))  # stands in for the decoded samples: only len() and slicing are used


class FakeEngines:
    def __init__(self, duration_s, languages, whisper_words=(), cohere_texts=()):
        self.audio = seconds(duration_s)
        self.languages = list(languages)
        self.whisper_words_out = list(whisper_words)
        self.cohere_texts_out = list(cohere_texts)
        self.calls = []

    def load_audio(self, audio_file):
        return self.audio

    def window_language(self, window):
        self.calls.append(("window", len(window)))
        return self.languages.pop(0)

    def whisper_words(self, audio, language):
        self.calls.append(("whisper", language))
        return self.whisper_words_out

    def cohere_texts(self, chunks):
        self.calls.append(("cohere", [len(c) / SAMPLE_RATE for c in chunks]))
        return self.cohere_texts_out

    def align(self, chunk, words, offset):
        self.calls.append(("align", words, offset))
        return [{"text": w, "start": offset + i, "end": offset + i + 0.5} for i, w in enumerate(words)]


def w(text, start):
    return {"text": text, "start": start, "end": start + 0.4}


class TestLanguageVote:
    def test_majority_of_windows_with_speech(self):
        engines = FakeEngines(100, ["en", None, "es", "es"])
        assert OpenModelTranscriber(engines).vote_language(engines.audio) == "es"
        assert [c for c in engines.calls if c[0] == "window"] == [("window", 30 * SAMPLE_RATE)] * 3 + [
            ("window", 10 * SAMPLE_RATE)
        ]

    def test_none_when_no_window_has_speech(self):
        engines = FakeEngines(40, [None, None])
        assert OpenModelTranscriber(engines).vote_language(engines.audio) is None


class TestWhisperRoute:
    def test_spanish_goes_to_whisper_with_the_voted_language(self):
        engines = FakeEngines(45, ["es", "es"], whisper_words=[w("hola", 1.0), w("mundo", 21.5)])
        result = OpenModelTranscriber(engines).transcribe("a.mp3")
        assert ("whisper", "es") in engines.calls
        assert result.model == WHISPER_LABEL
        assert result.windows == {0: "hola", 20: "mundo", 40: ""}
        assert result.timestamped_transcription.splitlines()[0] == "[00:00] hola"
        assert result.text == "hola mundo"
        assert result.duration_s == 45

    def test_no_vote_lets_whisper_detect(self):
        engines = FakeEngines(20, [None], whisper_words=[w("hi", 0)])
        OpenModelTranscriber(engines).transcribe("a.mp3")
        assert ("whisper", None) in engines.calls

    def test_words_are_nfkc_normalized_and_blank_words_dropped(self):
        engines = FakeEngines(20, ["en"], whisper_words=[w(" ﬁne ", 0.12345), w("  ", 1)])
        result = OpenModelTranscriber(engines).transcribe("a.mp3")
        assert result.words == [{"text": "fine", "start": 0.123, "end": 0.523, "speaker": None}]


class TestArabicRoute:
    def test_arabic_goes_to_cohere_then_the_aligner_per_20s_chunk(self):
        engines = FakeEngines(40.5, ["ar", "ar"], cohere_texts=["مرحبا، بكم!", "  "])
        result = OpenModelTranscriber(engines).transcribe("a.mp3")
        assert ("cohere", [20.0, 20.0]) in engines.calls  # the 0.5 s tail is dropped, as in the eval
        assert ("align", ["مرحبا", "بكم"], 0) in engines.calls
        assert ("align", [], 20) not in engines.calls
        assert result.model == ARABIC_LABEL
        assert result.windows[0] == "مرحبا بكم"


class TestEmptyTranscript:
    def test_long_audio_without_words_is_an_error(self):
        engines = FakeEngines(301, ["es"] * 11)
        with pytest.raises(ValueError, match="no words for 301 s"):
            OpenModelTranscriber(engines).transcribe("a.mp3")

    def test_short_audio_without_words_is_an_empty_transcript(self):
        engines = FakeEngines(25, [None])
        result = OpenModelTranscriber(engines).transcribe("a.mp3")
        assert result.words == [] and result.windows == {0: "", 20: ""}
