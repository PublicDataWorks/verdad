"""STAGE1_TRANSCRIPTION_METHOD=transcribe: gemini-3.5-transcribe word timestamps -> the segments path's format."""

import glob
import os
from unittest.mock import MagicMock, Mock, call, patch

import pytest
import requests
from pydub import AudioSegment

from processing_pipeline.constants import GeminiModel
from processing_pipeline.model_config import TranscriptionMethod
from processing_pipeline.stage_1 import transcribe_audio_file_with_timestamp_with_gemini
from processing_pipeline.stage_1.executors import GeminiTimestampTranscriptionGenerator
from processing_pipeline.stage_1.transcribe_executor import (
    INTERACTIONS_URL,
    REQUEST_TIMEOUT_SECONDS,
    GeminiTranscribeTimestampGenerator as Transcribe,
    TranscribeAPIError,
)

MODULE = "processing_pipeline.stage_1.transcribe_executor"


def word(text, start, end=None):
    end = start + 0.3 if end is None else end
    return {
        "type": "word_info",
        "text": text,
        "start_offset": f"{start}s",
        "end_offset": f"{end}s",
        "start_index": 0,
        "end_index": len(text),
    }


def interaction(*annotations, text="text", status="completed"):
    return {
        "status": status,
        "steps": [
            {"type": "model_output", "content": [{"type": "text", "text": text, "annotations": list(annotations)}]}
        ],
    }


def http_response(status_code, body=None, text=""):
    response = Mock(status_code=status_code, text=text)
    response.json.return_value = body
    return response


@pytest.fixture
def sample_audio_file(test_data_dir):
    """A 45-second silent mp3: three 20 s windows, the last one partial"""
    audio_path = os.path.join(test_data_dir, "stage_1_transcribe_audio.mp3")
    AudioSegment.silent(duration=45_000).export(audio_path, format="mp3")
    yield audio_path
    for path in glob.glob(f"{audio_path}*"):
        os.remove(path)


@pytest.fixture
def gemini_client():
    client = Mock()
    uploaded = Mock(uri="https://generativelanguage.googleapis.com/v1beta/files/abc", mime_type="audio/mp3")
    uploaded.name = "files/abc"
    uploaded.state.name = "ACTIVE"
    client.files.upload.return_value = uploaded
    return client


@pytest.fixture
def no_sleep():
    with patch(f"{MODULE}.time.sleep") as sleep:
        yield sleep


class TestExtractWords:
    def test_reads_word_info_annotations_in_order(self):
        mundo = {**word("mundo", 1.0), "start_offset": "1s"}  # whole seconds come back without a decimal
        response = interaction(word("Hola", 0.6), mundo, {"type": "citation", "text": "x"})
        assert Transcribe.extract_words(response) == [{"text": "Hola", "start": 0.6}, {"text": "mundo", "start": 1.0}]

    def test_offsets(self):
        assert Transcribe.parse_offset("12.300s") == 12.3
        assert Transcribe.parse_offset("1s") == 1.0
        assert Transcribe.parse_offset(None) is None
        assert Transcribe.parse_offset("soon") is None

    def test_untimed_word_stays_with_previous_word(self):
        untimed = {"type": "word_info", "text": "y"}
        words = Transcribe.extract_words(interaction(word("a", 25.0), untimed, word("b", 26.0)))
        assert words[1] == {"text": "y", "start": 25.0}

    def test_blank_words_are_dropped(self):
        assert Transcribe.extract_words(interaction(word("  ", 1.0), word("a", 2.0))) == [{"text": "a", "start": 2.0}]

    def test_words_across_several_steps_and_contents(self):
        response = {
            "status": "completed",
            "steps": [
                {"content": [{"text": "a", "annotations": [word("a", 1.0)]}]},
                {
                    "content": [
                        {"text": "b", "annotations": [word("b", 2.0)]},
                        {"text": "c", "annotations": [word("c", 3.0)]},
                    ]
                },
            ],
        }
        assert [w["text"] for w in Transcribe.extract_words(response)] == ["a", "b", "c"]

    def test_text_without_timestamps_fails_instead_of_piling_everything_at_zero(self):
        with pytest.raises(ValueError, match="without word timestamps"):
            Transcribe.extract_words(interaction(text="Hola mundo"))

    def test_silent_recording_is_no_words(self):
        assert Transcribe.extract_words(interaction(text="")) == []
        assert Transcribe.extract_words({"status": "completed", "steps": []}) == []

    def test_unfinished_interaction_fails(self):
        with pytest.raises(ValueError, match="'in_progress'"):
            Transcribe.extract_words(interaction(word("a", 1.0), status="in_progress"))


class TestBucketWords:
    def test_every_window_is_present_and_words_land_by_start(self):
        words = [{"text": "a", "start": 0.0}, {"text": "b", "start": 19.99}, {"text": "c", "start": 40.0}]
        assert Transcribe.bucket_words(words, 45_000, 20) == {1: "a b", 2: "", 3: "c"}

    @pytest.mark.parametrize(
        "duration_ms, windows",
        [(1_800_000, 90), (1_799_000, 90), (1_780_001, 90), (1_780_000, 89), (45_000, 3), (1, 1)],
    )
    def test_window_count_matches_the_segments_path(self, duration_ms, windows):
        # split_audio_into_segments makes one slice per started 20 s, i.e. ceil(duration / 20 s)
        assert len(Transcribe.bucket_words([], duration_ms, 20)) == windows
        assert len(range(0, duration_ms, 20_000)) == windows

    def test_timestamps_past_the_end_go_to_the_last_window(self):
        # The eval saw a 30 min file come back with word starts up to 2029.9 s
        words = [{"text": "late", "start": 2029.9}, {"text": "early", "start": -1.0}]
        windows = Transcribe.bucket_words(words, 1_800_000, 20)
        assert len(windows) == 90
        assert windows[90] == "late"
        assert windows[1] == "early"

    def test_empty_audio(self):
        assert Transcribe.bucket_words([{"text": "a", "start": 0}], 0, 20) == {}


class TestTrim:
    @pytest.mark.parametrize(
        "duration_ms, trim",
        [(1_800_000, True), (1_799_501, True), (1_799_500, False), (1_799_000, False), (45_000, False)],
    )
    def test_needs_trim(self, duration_ms, trim):
        assert Transcribe.needs_trim(duration_ms) is trim

    def test_trim_audio_copies_the_first_seconds(self, sample_audio_file):
        trimmed = Transcribe.trim_audio(sample_audio_file, 10)
        assert trimmed == f"{sample_audio_file}_trim.mp3"
        assert abs(len(AudioSegment.from_mp3(trimmed)) - 10_000) < 200


class TestRequest:
    def test_request_shape(self, no_sleep):
        with patch(f"{MODULE}.requests.post", return_value=http_response(200, {"status": "completed"})) as post:
            assert Transcribe.request_transcription("k", GeminiModel.GEMINI_3_5_TRANSCRIBE, "uri://a") == {
                "status": "completed"
            }

        post.assert_called_once_with(
            INTERACTIONS_URL,
            headers={"x-goog-api-key": "k", "content-type": "application/json"},
            json={
                "model": "models/gemini-3.5-transcribe",
                "input": [{"type": "audio", "uri": "uri://a", "mime_type": "audio/mp3"}],
                "generation_config": {
                    "transcription_config": {"mode": {"type": "verbatim", "timestamp_granularities": ["word"]}}
                },
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        no_sleep.assert_not_called()

    def test_models_prefix_is_not_doubled(self):
        body = Transcribe.build_request_body("models/gemini-3.5-transcribe", "u")
        assert body["model"] == "models/gemini-3.5-transcribe"

    @pytest.mark.parametrize("status", [429, 500, 503])
    def test_transient_status_is_retried(self, no_sleep, status):
        responses = [http_response(status, text="busy"), http_response(200, {"status": "completed"})]
        with patch(f"{MODULE}.requests.post", side_effect=responses) as post:
            Transcribe.request_transcription("k", "gemini-3.5-transcribe", "u")
        assert post.call_count == 2
        no_sleep.assert_called_once_with(30)

    def test_dropped_connection_is_retried(self, no_sleep):
        responses = [requests.ConnectionError("reset"), requests.Timeout("slow"), http_response(200, {})]
        with patch(f"{MODULE}.requests.post", side_effect=responses):
            Transcribe.request_transcription("k", "gemini-3.5-transcribe", "u")
        assert no_sleep.call_args_list == [call(30), call(60)]

    def test_gives_up_after_the_last_delay(self, no_sleep):
        with patch(f"{MODULE}.requests.post", return_value=http_response(503, text="overloaded")) as post:
            with pytest.raises(TranscribeAPIError, match="HTTP 503: overloaded") as excinfo:
                Transcribe.request_transcription("k", "gemini-3.5-transcribe", "u")
        assert excinfo.value.status_code == 503
        assert post.call_count == 4
        assert no_sleep.call_args_list == [call(30), call(60), call(120)]

    @pytest.mark.parametrize("status", [400, 401, 403, 404])
    def test_client_error_is_not_retried(self, no_sleep, status):
        with patch(f"{MODULE}.requests.post", return_value=http_response(status, text="bad")) as post:
            with pytest.raises(TranscribeAPIError) as excinfo:
                Transcribe.request_transcription("k", "gemini-3.5-transcribe", "u")
        assert excinfo.value.status_code == status
        assert post.call_count == 1
        no_sleep.assert_not_called()

    def test_api_key_is_not_in_the_error(self, no_sleep):
        with patch(
            f"{MODULE}.requests.post", return_value=http_response(400, text="Request contains an invalid argument")
        ):
            with pytest.raises(TranscribeAPIError) as excinfo:
                Transcribe.request_transcription("secret-key", "gemini-3.5-transcribe", "u")
        assert "secret-key" not in str(excinfo.value)


class TestRun:
    def test_output_matches_the_segments_format(self, sample_audio_file, gemini_client, no_sleep):
        response = interaction(word("Hola", 0.6), word("mundo,", 19.4), word("adiós.", 41.0))
        with patch(f"{MODULE}.requests.post", return_value=http_response(200, response)) as post:
            text = Transcribe.run(gemini_client, sample_audio_file, GeminiModel.GEMINI_3_5_TRANSCRIBE, api_key="k")

        assert text == "[00:00] Hola mundo,\n[00:20] \n[00:40] adiós.\n"
        assert text == GeminiTimestampTranscriptionGenerator.format_final_transcription(
            {1: "Hola mundo,", 2: "", 3: "adiós."}, 20
        )
        upload_kwargs = gemini_client.files.upload.call_args.kwargs
        assert upload_kwargs["file"] == sample_audio_file  # 45 s: no trim
        assert upload_kwargs["config"].mime_type == "audio/mp3"
        assert post.call_args.kwargs["json"]["input"][0]["uri"] == gemini_client.files.upload.return_value.uri
        gemini_client.files.delete.assert_called_once_with(name="files/abc")
        gemini_client.models.generate_content.assert_not_called()

    def test_api_key_comes_from_env(self, sample_audio_file, gemini_client, no_sleep, monkeypatch):
        monkeypatch.setenv("GOOGLE_GEMINI_KEY", "env-key")
        with patch(f"{MODULE}.requests.post", return_value=http_response(200, interaction(text=""))) as post:
            Transcribe.run(gemini_client, sample_audio_file, GeminiModel.GEMINI_3_5_TRANSCRIBE)
        assert post.call_args.kwargs["headers"]["x-goog-api-key"] == "env-key"

    def test_missing_api_key(self, sample_audio_file, gemini_client, monkeypatch):
        monkeypatch.delenv("GOOGLE_GEMINI_KEY")
        with pytest.raises(ValueError, match="GOOGLE_GEMINI_KEY"):
            Transcribe.run(gemini_client, sample_audio_file, GeminiModel.GEMINI_3_5_TRANSCRIBE)
        gemini_client.files.upload.assert_not_called()

    def test_full_length_recording_is_trimmed_and_keeps_90_lines(self, sample_audio_file, gemini_client, no_sleep):
        audio = MagicMock()
        audio.__len__.return_value = 1_800_000
        trimmed_path = f"{sample_audio_file}_trim.mp3"

        def fake_trim(path, seconds):
            assert (path, seconds) == (sample_audio_file, 1799)
            open(trimmed_path, "wb").close()
            return trimmed_path

        response = interaction(word("primero", 0.2), word("último", 1798.8), word("fantasma", 2029.9))
        with (
            patch(f"{MODULE}.AudioSegment.from_mp3", return_value=audio),
            patch.object(Transcribe, "trim_audio", side_effect=fake_trim),
            patch(f"{MODULE}.requests.post", return_value=http_response(200, response)),
        ):
            text = Transcribe.run(gemini_client, sample_audio_file, GeminiModel.GEMINI_3_5_TRANSCRIBE, api_key="k")

        assert gemini_client.files.upload.call_args.kwargs["file"] == trimmed_path
        assert not os.path.exists(trimmed_path)
        lines = text.splitlines()
        assert len(lines) == 90
        assert lines[0] == "[00:00] primero"
        assert lines[1] == "[00:20] "
        assert lines[-1] == "[29:40] último fantasma"

    def test_trimmed_copy_and_upload_are_removed_when_the_request_fails(
        self, sample_audio_file, gemini_client, no_sleep
    ):
        audio = MagicMock()
        audio.__len__.return_value = 1_800_000
        with (
            patch(f"{MODULE}.AudioSegment.from_mp3", return_value=audio),
            patch(f"{MODULE}.requests.post", return_value=http_response(400, text="bad")),
        ):
            with pytest.raises(TranscribeAPIError):
                Transcribe.run(gemini_client, sample_audio_file, GeminiModel.GEMINI_3_5_TRANSCRIBE, api_key="k")

        assert not os.path.exists(f"{sample_audio_file}_trim.mp3")
        gemini_client.files.delete.assert_called_once_with(name="files/abc")
        assert os.path.exists(sample_audio_file)

    def test_waits_for_the_upload_to_finish_processing(self, sample_audio_file, gemini_client, no_sleep):
        processing = Mock(uri="u")
        processing.name = "files/abc"
        processing.state.name = "PROCESSING"
        gemini_client.files.upload.return_value = processing
        active = Mock(uri="u-active")
        active.name = "files/abc"
        active.state.name = "ACTIVE"
        gemini_client.files.get.return_value = active

        with patch(f"{MODULE}.requests.post", return_value=http_response(200, interaction(text=""))) as post:
            Transcribe.run(gemini_client, sample_audio_file, GeminiModel.GEMINI_3_5_TRANSCRIBE, api_key="k")

        gemini_client.files.get.assert_called_once_with(name="files/abc")
        assert post.call_args.kwargs["json"]["input"][0]["uri"] == "u-active"

    def test_failed_upload_is_deleted_and_not_sent(self, sample_audio_file, gemini_client, no_sleep):
        gemini_client.files.upload.return_value.state.name = "FAILED"
        with patch(f"{MODULE}.requests.post") as post:
            with pytest.raises(ValueError, match="could not process"):
                Transcribe.run(gemini_client, sample_audio_file, GeminiModel.GEMINI_3_5_TRANSCRIBE, api_key="k")
        post.assert_not_called()
        gemini_client.files.delete.assert_called_once_with(name="files/abc")


class TestTaskDispatch:
    PROMPT_VERSION = {"id": "pv-1", "user_prompt": "p", "system_instruction": "s", "output_schema": {}}

    def test_transcribe_method_from_env(self, monkeypatch):
        monkeypatch.setenv("STAGE1_TRANSCRIPTION_METHOD", "transcribe")
        client = Mock()
        with patch(
            "processing_pipeline.stage_1.tasks.GeminiTranscribeTimestampGenerator.run", return_value="[00:00] hola\n"
        ) as run, patch("processing_pipeline.stage_1.tasks.GeminiTimestampTranscriptionGenerator.run") as segments:
            result = transcribe_audio_file_with_timestamp_with_gemini(
                client, "a.mp3", self.PROMPT_VERSION, GeminiModel.GEMINI_3_5_TRANSCRIBE
            )

        assert result == {"timestamped_transcription": "[00:00] hola\n"}
        run.assert_called_once_with(
            gemini_client=client, audio_file="a.mp3", model_name=GeminiModel.GEMINI_3_5_TRANSCRIBE, segment_length=20
        )
        segments.assert_not_called()

    def test_explicit_method_wins_over_env(self, monkeypatch):
        monkeypatch.setenv("STAGE1_TRANSCRIPTION_METHOD", "transcribe")
        with patch("processing_pipeline.stage_1.tasks.GeminiTranscribeTimestampGenerator.run") as run, patch(
            "processing_pipeline.stage_1.tasks.GeminiTimestampTranscriptionGenerator.run", return_value="[00:00] x\n"
        ) as segments:
            transcribe_audio_file_with_timestamp_with_gemini(
                Mock(), "a.mp3", self.PROMPT_VERSION, GeminiModel.GEMINI_2_5_FLASH, method=TranscriptionMethod.SEGMENTS
            )
        run.assert_not_called()
        assert segments.call_args.kwargs["prompt_version"] == self.PROMPT_VERSION

    def test_transcribe_method_needs_a_client(self):
        with pytest.raises(ValueError, match="Gemini client is not provided"):
            transcribe_audio_file_with_timestamp_with_gemini(
                None, "a.mp3", self.PROMPT_VERSION, "gemini-3.5-transcribe", method=TranscriptionMethod.TRANSCRIBE
            )
