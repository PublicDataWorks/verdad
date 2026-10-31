"""STAGE1_ANCHOR_TIMESTAMPS: flagged snippet times from Transcribe word timestamps."""

import pytest

from processing_pipeline.stage_1.anchor import (
    Anchor,
    anchor_flagged_snippets,
    anchor_snippet,
    format_clock,
    normalize,
    parse_clock,
    tokenize,
)

FILLER = "la radio comunitaria presenta las noticias de la mañana con música y saludos para todos los oyentes".split()


def timed(text: str, start: float, step: float = 0.5) -> list[dict]:
    """One word every ``step`` seconds from ``start``, each lasting ``step * 0.8``."""
    return [
        {"text": token, "start": start + i * step, "end": start + i * step + step * 0.8, "speaker": None}
        for i, token in enumerate(text.split())
    ]


def recording(*pieces: tuple[float, str]) -> list[dict]:
    """Filler talk from 0 s to 400 s with each ``(start, text)`` piece laid over it."""
    words = []
    t = 0.0
    while t < 400:
        for token in FILLER:
            words.append({"text": token, "start": t, "end": t + 0.4, "speaker": None})
            t += 0.5
    for start, text in pieces:
        piece = timed(text, start)
        end = piece[-1]["end"]
        words = [w for w in words if not (start <= w["start"] <= end)] + piece
    return sorted(words, key=lambda w: w["start"])


CLAIM = "El gobierno quiere controlar a la población con las vacunas que nos ponen"


class TestNormalize:
    def test_case_punctuation_and_accents(self):
        assert normalize("¡Él,") == "el"
        assert normalize("POBLACIÓN.") == "poblacion"
        assert normalize("D.C.") == "dc"
        assert normalize("...") == ""

    def test_arabic_harakat_are_ignored(self):
        assert normalize("كَتَبَ") == normalize("كتب")

    def test_tokenize_drops_punctuation_only_tokens(self):
        assert tokenize("Hola , mundo — ¿sí?") == ["hola", "mundo", "si"]
        assert tokenize(None) == []


class TestClock:
    @pytest.mark.parametrize(
        "value, seconds",
        [("05:30", 330.0), ("1:02:03", 3723.0), ("45", 45.0), ("00:07.5", 7.5), (" 07:15 ", 435.0)],
    )
    def test_parse(self, value, seconds):
        assert parse_clock(value) == seconds

    @pytest.mark.parametrize("value", [None, "", "abc", "1:2:3:4", "05:xx"])
    def test_parse_rejects(self, value):
        assert parse_clock(value) is None

    def test_format(self):
        assert format_clock(0) == "00:00"
        assert format_clock(65) == "01:05"
        assert format_clock(1799) == "29:59"
        assert format_clock(3725) == "62:05"
        assert format_clock(-3) == "00:00"


class TestAnchorSnippet:
    def test_exact_match(self):
        words = recording((123.0, CLAIM))
        anchor = anchor_snippet(CLAIM, words, llm_start_s=120, llm_end_s=140)

        assert anchor.accepted and anchor.reason == "matched"
        assert anchor.score == pytest.approx(1.0)
        assert anchor.start_s == 123.0
        claim_words = len(CLAIM.split())
        assert anchor.end_s == pytest.approx(123.0 + (claim_words - 1) * 0.5 + 0.4)

    def test_fuzzy_match_with_fillers_accents_and_punctuation(self):
        spoken = "pues eh el gobierno este quiere controlar eh a la poblacion con las vacunas que nos ponen o sea"
        words = recording((200.0, spoken))
        anchor = anchor_snippet(
            "¡El gobierno quiere controlar a la población con las vacunas que nos ponen!", words, 180, 200
        )

        assert anchor.accepted
        assert 0.6 <= anchor.score < 1.0
        assert anchor.start_s == pytest.approx(200.0 + 2 * 0.5)  # "el", after "pues eh"
        assert anchor.end_s == pytest.approx(200.0 + 16 * 0.5 + 0.4)  # "ponen", before "o sea"

    def test_no_match_keeps_the_model_times(self):
        words = recording((123.0, CLAIM))
        anchor = anchor_snippet("los extraterrestres construyeron las pirámides de Egipto", words, 120, 140)

        assert anchor == Anchor(None, None, anchor.score, False, "low_score")
        assert anchor.score < 0.6

    def test_match_outside_the_window_is_rejected(self):
        words = recording((300.0, CLAIM))
        anchor = anchor_snippet(CLAIM, words, llm_start_s=20, llm_end_s=40)

        assert not anchor.accepted
        assert anchor.reason == "out_of_window"
        assert anchor.start_s == 300.0  # where it was found, for diagnostics only

    def test_tolerance_edges(self):
        words = recording((101.0, CLAIM))
        assert anchor_snippet(CLAIM, words, 160, 180).accepted  # 101 >= 160 - 60
        assert not anchor_snippet(CLAIM, words, 170, 180).accepted  # 101 < 170 - 60

    def test_repeated_phrase_takes_the_copy_near_the_model_window(self):
        words = recording((50.0, CLAIM), (310.0, CLAIM))
        anchor = anchor_snippet(CLAIM, words, 300, 320)
        assert anchor.accepted and anchor.start_s == 310.0

    def test_swapped_model_times_still_define_the_window(self):
        words = recording((123.0, CLAIM))
        assert anchor_snippet(CLAIM, words, llm_start_s=140, llm_end_s=120).accepted

    def test_empty_inputs(self):
        assert anchor_snippet("", recording(), 0, 20).reason == "empty_transcription"
        assert anchor_snippet("¿?", recording(), 0, 20).reason == "empty_transcription"
        assert anchor_snippet(CLAIM, [], 0, 20).reason == "no_words"

    def test_words_without_text_are_skipped(self):
        words = [{"text": "...", "start": 1.0, "end": 1.2}, *timed(CLAIM, 2.0)]
        assert anchor_snippet(CLAIM, words, 0, 20).start_s == 2.0

    def test_window_with_only_punctuation_words(self):
        words = [{"text": "...", "start": 1.0, "end": 1.2}]
        assert anchor_snippet(CLAIM, words, 0, 20).reason == "low_score"


class TestAnchorFlaggedSnippets:
    def test_accepted_anchor_rewrites_the_times_and_keeps_the_model_ones(self):
        words = recording((65.4, CLAIM))
        snippet = {"uuid": "u1", "start_time": "01:00", "end_time": "01:20", "transcription": CLAIM}

        (anchor,) = anchor_flagged_snippets([snippet], words)

        assert anchor.accepted
        end_s = 65.4 + (len(CLAIM.split()) - 1) * 0.5 + 0.4  # 13 words: 71.8
        assert snippet == {
            "uuid": "u1",
            "transcription": CLAIM,
            "start_time": "01:05",  # 65.4 rounded down
            "end_time": "01:12",  # 71.8 rounded up
            "start_s": 65.4,
            "end_s": round(end_s, 3),
            "anchor_score": 1.0,
            "anchor_status": "matched",
            "llm_start_time": "01:00",
            "llm_end_time": "01:20",
        }

    def test_whole_second_times_are_not_widened(self):
        words = [{"text": "hola", "start": 10.0, "end": 11.0}, {"text": "mundo", "start": 11.0, "end": 12.0}]
        snippet = {"start_time": "00:00", "end_time": "00:20", "transcription": "hola mundo"}
        anchor_flagged_snippets([snippet], words)
        assert (snippet["start_time"], snippet["end_time"]) == ("00:10", "00:12")

    def test_rejected_anchor_keeps_the_model_times(self):
        words = recording((300.0, CLAIM))
        snippet = {"start_time": "00:20", "end_time": "00:40", "transcription": CLAIM}

        anchor_flagged_snippets([snippet], words)

        assert (snippet["start_time"], snippet["end_time"]) == ("00:20", "00:40")
        assert (snippet["llm_start_time"], snippet["llm_end_time"]) == ("00:20", "00:40")
        assert snippet["start_s"] is None and snippet["end_s"] is None
        assert snippet["anchor_status"] == "out_of_window"
        assert snippet["anchor_score"] == 1.0

    def test_unparseable_model_times_are_left_alone(self):
        snippet = {"start_time": "soon", "end_time": "00:40", "transcription": CLAIM}
        (anchor,) = anchor_flagged_snippets([snippet], recording((20.0, CLAIM)))
        assert anchor.reason == "unparseable_llm_times"
        assert snippet["start_time"] == "soon"
        assert snippet["anchor_score"] == 0.0
