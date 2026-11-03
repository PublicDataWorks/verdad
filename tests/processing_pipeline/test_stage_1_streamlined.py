"""Streamlined Stage 1: STAGE1_TRANSCRIBE_FIRST, STAGE1_DETECTION_PASSES and STAGE1_ANCHOR_TIMESTAMPS."""

import glob
import os
import uuid
from unittest.mock import ANY, Mock, patch

import pytest
from pydub import AudioSegment

from processing_pipeline.constants import GeminiModel, ProcessingStatus
from processing_pipeline.stage_1 import (
    disinformation_detection_with_gemini,
    get_audio_file_metadata,
    initial_disinformation_detection,
    process_audio_file,
    redo_main_detection,
)
from processing_pipeline.stage_1.tasks import (
    transcribe_audio_file_with_gemini_transcribe,
    transcribe_audio_file_with_open_models,
)
from processing_pipeline.stage_1.transcribe_executor import TranscribeResult

TASKS = "processing_pipeline.stage_1.tasks"

PROMPT_VERSION = {"id": "pv-1", "user_prompt": "prompt", "system_instruction": "system", "output_schema": {}}

AUDIO_FILE = {
    "id": 1,
    "file_path": "test/path.mp3",
    "radio_station_name": "Test Station",
    "radio_station_code": "TEST-FM",
    "location_state": "Test State",
    "location_city": "Test City",
    "recorded_at": "2024-01-01T00:00:00+00:00",
    "recording_day_of_week": "Monday",
}

CLAIM = "las vacunas tienen un chip para controlar a la gente"
WORDS = [
    {"text": token, "start": 61.2 + i * 0.5, "end": 61.6 + i * 0.5, "speaker": None}
    for i, token in enumerate(f"buenos días {CLAIM} eso dicen".split())
]
TRANSCRIPT = TranscribeResult(
    text=f"Buenos días, {CLAIM}, eso dicen.",
    windows={0: "", 20: "", 40: "", 60: f"buenos días {CLAIM} eso dicen"},
    timestamped_transcription=f"[00:00] \n[00:20] \n[00:40] \n[01:00] buenos días {CLAIM} eso dicen\n",
    words=WORDS,
    duration_s=80.0,
)


@pytest.fixture
def streamlined(monkeypatch):
    monkeypatch.setenv("STAGE1_TRANSCRIPTION_METHOD", "transcribe")
    monkeypatch.setenv("STAGE1_TRANSCRIBE_FIRST", "true")


@pytest.fixture
def mock_tasks():
    with (
        patch(f"{TASKS}.initial_transcription_with_gemini") as initial_transcription,
        patch(f"{TASKS}.transcribe_audio_file_with_timestamp_with_gemini") as segments_or_legacy,
        patch(f"{TASKS}.transcribe_audio_file_with_gemini_transcribe", return_value=TRANSCRIPT) as transcribe,
        patch(f"{TASKS}.fetch_kb_context", return_value="kb context") as kb_context,
        patch(f"{TASKS}.initial_disinformation_detection_with_gemini") as initial_detection,
        patch(f"{TASKS}.disinformation_detection_with_gemini") as detect,
    ):
        initial_detection.return_value = {"flagged_snippets": [{"transcription": "maybe"}]}
        detect.return_value = {"flagged_snippets": [{"uuid": "u1"}]}
        yield {
            "initial_transcription": initial_transcription,
            "legacy_timestamped": segments_or_legacy,
            "transcribe": transcribe,
            "kb_context": kb_context,
            "initial_detection": initial_detection,
            "detect": detect,
        }


def run(supabase_client, gemini_client=None, openai_client=None, local_file="test.mp3", prompts=None):
    prompts = prompts or {}
    process_audio_file(
        supabase_client=supabase_client,
        gemini_client=gemini_client or Mock(),
        openai_client=openai_client or Mock(),
        audio_file=AUDIO_FILE,
        local_file=local_file,
        initial_transcription_prompt_version={**PROMPT_VERSION, "id": "pv-it"},
        initial_detection_prompt_version={**PROMPT_VERSION, "id": "pv-id", **prompts.get("initial", {})},
        transcription_prompt_version={**PROMPT_VERSION, "id": "pv-tt"},
        detection_prompt_version={**PROMPT_VERSION, "id": "pv-dd", **prompts.get("main", {})},
    )


class TestTranscribeFirstTwoPasses:
    def test_flagged_recording_reuses_the_one_transcript(self, streamlined, mock_tasks):
        supabase, gemini, openai = Mock(), Mock(), Mock()

        run(supabase, gemini, openai)

        mock_tasks["transcribe"].assert_called_once_with(
            gemini_client=gemini, audio_file="test.mp3", model_name=GeminiModel.GEMINI_3_5_TRANSCRIBE
        )
        mock_tasks["initial_transcription"].assert_not_called()  # no whole-file upload to a chat model
        mock_tasks["legacy_timestamped"].assert_not_called()  # no second audio call when flagged
        mock_tasks["kb_context"].assert_called_once_with(supabase, openai, TRANSCRIPT.text)
        assert mock_tasks["initial_detection"].call_args.kwargs["initial_transcription"] == TRANSCRIPT.text
        mock_tasks["detect"].assert_called_once_with(
            gemini_client=gemini,
            timestamped_transcription=TRANSCRIPT.timestamped_transcription,
            metadata=get_audio_file_metadata(AUDIO_FILE),
            prompt_version={**PROMPT_VERSION, "id": "pv-dd"},
            model_name=GeminiModel.GEMINI_2_5_FLASH,
            kb_context="kb context",
            words=WORDS,
        )
        supabase.insert_stage_1_llm_response.assert_called_once_with(
            audio_file_id=1,
            initial_transcription=TRANSCRIPT.text,
            initial_detection_result={"flagged_snippets": [{"transcription": "maybe"}]},
            transcriptor=GeminiModel.GEMINI_3_5_TRANSCRIBE,
            timestamped_transcription={
                "timestamped_transcription": TRANSCRIPT.timestamped_transcription,
                "words": WORDS,
            },
            detection_result={"flagged_snippets": [{"uuid": "u1"}]},
            status="New",
            detection_prompt_version_id="pv-dd",
            transcription_prompt_version_id=None,  # Transcribe takes no prompt
        )
        supabase.set_audio_file_status.assert_called_once_with(1, ProcessingStatus.PROCESSED, None)

    def test_unflagged_recording_still_records_the_transcriptor(self, streamlined, mock_tasks):
        mock_tasks["initial_detection"].return_value = {"flagged_snippets": []}
        supabase = Mock()

        run(supabase)

        mock_tasks["detect"].assert_not_called()
        supabase.insert_stage_1_llm_response.assert_called_once_with(
            audio_file_id=1,
            initial_transcription=TRANSCRIPT.text,
            initial_detection_result={"flagged_snippets": []},
            transcriptor=GeminiModel.GEMINI_3_5_TRANSCRIBE,
            timestamped_transcription=None,
            detection_result=None,
            status="Processed",
            detection_prompt_version_id=None,
            transcription_prompt_version_id=None,
        )
        supabase.set_audio_file_status.assert_called_once_with(1, ProcessingStatus.PROCESSED, None)

    def test_main_detection_without_flags_is_processed(self, streamlined, mock_tasks):
        mock_tasks["detect"].return_value = {"flagged_snippets": []}
        supabase = Mock()

        run(supabase)

        stored = supabase.insert_stage_1_llm_response.call_args.kwargs
        assert stored["status"] == "Processed"
        assert stored["timestamped_transcription"]["words"] == WORDS

    def test_timestamp_model_override_is_the_transcriptor(self, streamlined, mock_tasks, monkeypatch):
        monkeypatch.setenv("STAGE1_TIMESTAMP_MODEL", "gemini-3.6-transcribe-preview")
        supabase = Mock()

        run(supabase)

        assert mock_tasks["transcribe"].call_args.kwargs["model_name"] == "gemini-3.6-transcribe-preview"
        assert supabase.insert_stage_1_llm_response.call_args.kwargs["transcriptor"] == "gemini-3.6-transcribe-preview"

    def test_transcribe_failure_marks_the_audio_file(self, streamlined, mock_tasks):
        mock_tasks["transcribe"].side_effect = ValueError("The transcription came back without word timestamps")
        supabase = Mock()

        run(supabase)

        mock_tasks["initial_detection"].assert_not_called()
        supabase.insert_stage_1_llm_response.assert_not_called()
        supabase.set_audio_file_status.assert_called_once_with(
            1, ProcessingStatus.ERROR, "The transcription came back without word timestamps"
        )


class TestOpenModels:
    @pytest.fixture
    def open_models(self, monkeypatch):
        monkeypatch.setenv("STAGE1_TRANSCRIPTION_METHOD", "open_model")
        monkeypatch.setenv("STAGE1_TRANSCRIBE_FIRST", "true")
        result = TranscribeResult(**{**TRANSCRIPT.__dict__, "model": "faster-whisper-large-v3"})
        with patch(f"{TASKS}.transcribe_audio_file_with_open_models", return_value=result) as open_models:
            yield open_models

    def test_transcript_comes_from_the_open_models(self, open_models, mock_tasks):
        supabase = Mock()

        run(supabase)

        open_models.assert_called_once_with(audio_file="test.mp3")
        mock_tasks["transcribe"].assert_not_called()
        mock_tasks["kb_context"].assert_called_once_with(supabase, ANY, TRANSCRIPT.text)
        stored = supabase.insert_stage_1_llm_response.call_args.kwargs
        assert stored["transcriptor"] == "faster-whisper-large-v3"
        assert stored["timestamped_transcription"]["words"] == WORDS

    def test_task_fails_clearly_without_the_gpu_dependencies(self):
        with patch(f"{TASKS}.GpuEngines", None), pytest.raises(RuntimeError, match="requirements-gpu.txt"):
            transcribe_audio_file_with_open_models(audio_file="a.mp3")


def test_transcribe_first_task_needs_a_client():
    with pytest.raises(ValueError, match="Gemini client is not provided"):
        transcribe_audio_file_with_gemini_transcribe(None, "a.mp3", GeminiModel.GEMINI_3_5_TRANSCRIBE)


class TestDetectionPasses:
    def test_one_pass_skips_initial_detection(self, streamlined, mock_tasks, monkeypatch):
        monkeypatch.setenv("STAGE1_DETECTION_PASSES", "one")
        mock_tasks["detect"].return_value = {"flagged_snippets": []}
        supabase = Mock()

        run(supabase)

        mock_tasks["initial_detection"].assert_not_called()
        mock_tasks["detect"].assert_called_once()
        stored = supabase.insert_stage_1_llm_response.call_args.kwargs
        assert stored["initial_detection_result"] is None
        assert stored["initial_transcription"] == TRANSCRIPT.text
        assert stored["transcriptor"] == GeminiModel.GEMINI_3_5_TRANSCRIBE
        assert stored["detection_result"] == {"flagged_snippets": []}
        assert stored["status"] == "Processed"

    def test_one_pass_flagged_is_new(self, streamlined, mock_tasks, monkeypatch):
        monkeypatch.setenv("STAGE1_DETECTION_PASSES", "one")
        supabase = Mock()

        run(supabase)

        assert supabase.insert_stage_1_llm_response.call_args.kwargs["status"] == "New"

    def test_two_passes_is_the_default(self, streamlined, mock_tasks):
        run(Mock())
        mock_tasks["initial_detection"].assert_called_once()

    def test_one_pass_without_transcribe_first_fails_the_file(self, mock_tasks, monkeypatch):
        monkeypatch.setenv("STAGE1_DETECTION_PASSES", "one")
        supabase = Mock()

        run(supabase)

        mock_tasks["initial_transcription"].assert_not_called()
        status = supabase.set_audio_file_status.call_args.args
        assert status[1] == ProcessingStatus.ERROR
        assert "STAGE1_TRANSCRIBE_FIRST=true" in status[2]


class TestDefaultsAreUnchanged:
    def test_transcribe_first_off_runs_todays_flow(self, mock_tasks, monkeypatch):
        monkeypatch.setenv("STAGE1_TRANSCRIPTION_METHOD", "transcribe")  # method alone does not change the shape
        mock_tasks["initial_transcription"].return_value = "untimed"
        mock_tasks["legacy_timestamped"].return_value = {"timestamped_transcription": "[00:00] x"}

        run(Mock())

        mock_tasks["transcribe"].assert_not_called()
        mock_tasks["initial_transcription"].assert_called_once()
        mock_tasks["legacy_timestamped"].assert_called_once()
        assert "words" not in mock_tasks["detect"].call_args.kwargs


@pytest.fixture
def sample_audio_file(test_data_dir):
    path = os.path.join(test_data_dir, "streamlined.mp3")
    AudioSegment.silent(duration=80_000).export(path, format="mp3")
    yield path
    for leftover in glob.glob(f"{path}*"):
        os.remove(leftover)


def interaction_response():
    annotations = [
        {"type": "word_info", "text": w["text"], "start_offset": f"{w['start']}s", "end_offset": f"{w['end']}s"}
        for w in WORDS
    ]
    content = {"type": "text", "text": TRANSCRIPT.text, "annotations": annotations}
    return Mock(status_code=200, json=Mock(return_value={"status": "completed", "steps": [{"content": [content]}]}))


def stored_transcript():
    lines = ["[00:00] ", "[00:20] ", "[00:40] ", f"[01:00] buenos días {CLAIM} eso dicen"]
    return "\n".join(lines) + "\n"


class TestEndToEnd:
    """Real executors and tasks; only the HTTP call, the Gemini client and KB retrieval are fakes."""

    @pytest.fixture
    def gemini_client(self):
        client = Mock()
        uploaded = Mock(uri="https://generativelanguage.googleapis.com/v1beta/files/abc")
        uploaded.name = "files/abc"
        uploaded.state.name = "ACTIVE"
        client.files.upload.return_value = uploaded
        return client

    def _flag(self, start, end):
        return {
            "flagged_snippets": [
                {
                    "start_time": start,
                    "end_time": end,
                    "transcription": CLAIM,
                    "explanation": "x",
                    "disinformation_categories": [],
                    "keywords_detected": [],
                }
            ]
        }

    def _run(self, gemini_client, sample_audio_file, detection_outputs):
        gemini_client.models.generate_content.side_effect = [Mock(parsed=o) for o in detection_outputs]
        supabase = Mock()
        with (
            patch(
                "processing_pipeline.stage_1.transcribe_executor.requests.post", return_value=interaction_response()
            ) as post,
            patch(f"{TASKS}.fetch_kb_context", return_value=None),
        ):
            run(
                supabase,
                gemini_client,
                local_file=sample_audio_file,
                prompts={
                    "initial": {"user_prompt": "INITIAL {transcription}"},
                    "main": {"user_prompt": "MAIN {timestamped_transcription}"},
                },
            )
        return supabase, post

    def test_flagged_recording_makes_one_audio_call(self, streamlined, gemini_client, sample_audio_file, monkeypatch):
        monkeypatch.setenv("STAGE1_ANCHOR_TIMESTAMPS", "true")

        supabase, post = self._run(
            gemini_client,
            sample_audio_file,
            [{"flagged_snippets": [{"transcription": CLAIM}]}, self._flag("01:00", "01:20")],
        )

        # one upload + one Transcribe request; the two generate_content calls are the text-only detections
        gemini_client.files.upload.assert_called_once()
        post.assert_called_once()
        assert gemini_client.models.generate_content.call_count == 2
        for call in gemini_client.models.generate_content.call_args_list:
            assert all(isinstance(part, str) for part in call.kwargs["contents"])
        prompts = [c.kwargs["contents"][0] for c in gemini_client.models.generate_content.call_args_list]
        assert prompts == [f"INITIAL {TRANSCRIPT.text}", "MAIN " + stored_transcript()]

        stored = supabase.insert_stage_1_llm_response.call_args.kwargs
        assert stored["transcriptor"] == GeminiModel.GEMINI_3_5_TRANSCRIBE
        assert stored["initial_transcription"] == TRANSCRIPT.text
        assert stored["timestamped_transcription"]["timestamped_transcription"] == stored_transcript()
        assert len(stored["timestamped_transcription"]["words"]) == len(WORDS)
        snippet = stored["detection_result"]["flagged_snippets"][0]
        uuid.UUID(snippet["uuid"])
        # "las" at 62.2 s, "gente" ends at 62.2 + 9 * 0.5 + 0.4 = 67.1 s
        assert (snippet["start_time"], snippet["end_time"]) == ("01:02", "01:08")
        assert (snippet["llm_start_time"], snippet["llm_end_time"]) == ("01:00", "01:20")
        assert snippet["anchor_status"] == "matched"
        assert stored["status"] == "New"
        supabase.set_audio_file_status.assert_called_once_with(1, ProcessingStatus.PROCESSED, None)

    def test_unflagged_recording_makes_one_audio_call_and_one_text_call(
        self, streamlined, gemini_client, sample_audio_file
    ):
        supabase, post = self._run(gemini_client, sample_audio_file, [{"flagged_snippets": []}])

        gemini_client.files.upload.assert_called_once()
        post.assert_called_once()
        gemini_client.models.generate_content.assert_called_once()
        assert (
            supabase.insert_stage_1_llm_response.call_args.kwargs["transcriptor"] == GeminiModel.GEMINI_3_5_TRANSCRIBE
        )

    def test_one_pass_makes_one_audio_call_and_one_text_call(
        self, streamlined, gemini_client, sample_audio_file, monkeypatch
    ):
        monkeypatch.setenv("STAGE1_DETECTION_PASSES", "one")

        supabase, post = self._run(gemini_client, sample_audio_file, [self._flag("01:00", "01:20")])

        post.assert_called_once()
        gemini_client.models.generate_content.assert_called_once()
        stored = supabase.insert_stage_1_llm_response.call_args.kwargs
        assert stored["initial_detection_result"] is None
        snippet = stored["detection_result"]["flagged_snippets"][0]
        assert (snippet["start_time"], snippet["end_time"]) == ("01:00", "01:20")  # anchoring is off
        assert "llm_start_time" not in snippet


class TestAnchoringInDetection:
    def _detect(self, words, start="01:00", end="01:20"):
        with patch(f"{TASKS}.Stage1Executor") as executor:
            executor.run.return_value = {
                "flagged_snippets": [{"start_time": start, "end_time": end, "transcription": CLAIM}]
            }
            return disinformation_detection_with_gemini(
                Mock(), "[01:00] ...", {}, PROMPT_VERSION, GeminiModel.GEMINI_2_5_FLASH, words=words
            )["flagged_snippets"][0]

    def test_anchors_when_enabled_and_words_exist(self, monkeypatch):
        monkeypatch.setenv("STAGE1_ANCHOR_TIMESTAMPS", "true")
        snippet = self._detect(WORDS)
        assert (snippet["start_time"], snippet["end_time"], snippet["start_s"]) == ("01:02", "01:08", 62.2)

    def test_off_by_default(self):
        snippet = self._detect(WORDS)
        assert (snippet["start_time"], snippet["end_time"]) == ("01:00", "01:20")
        assert "anchor_score" not in snippet

    def test_no_words_no_anchoring(self, monkeypatch):
        monkeypatch.setenv("STAGE1_ANCHOR_TIMESTAMPS", "true")
        assert "anchor_score" not in self._detect(None)

    def test_out_of_window_keeps_the_model_times(self, monkeypatch):
        monkeypatch.setenv("STAGE1_ANCHOR_TIMESTAMPS", "true")
        snippet = self._detect(WORDS, start="05:00", end="05:20")
        assert (snippet["start_time"], snippet["end_time"]) == ("05:00", "05:20")
        assert snippet["anchor_status"] == "out_of_window"


class TestFlowStart:
    @pytest.fixture
    def env(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_GEMINI_KEY", "test-key")
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    def test_invalid_combination_fails_before_any_client(self, env, monkeypatch):
        monkeypatch.setenv("STAGE1_DETECTION_PASSES", "one")
        with (
            patch("processing_pipeline.stage_1.flows.SupabaseClient") as supabase,
            patch("boto3.client") as boto,
            pytest.raises(ValueError, match="STAGE1_DETECTION_PASSES=one needs STAGE1_TRANSCRIBE_FIRST=true"),
        ):
            initial_disinformation_detection(audio_file_id=None, limit=1)
        supabase.assert_not_called()
        boto.assert_not_called()

    def test_redo_main_detection_anchors_with_the_stored_words(self, env, monkeypatch):
        monkeypatch.setenv("STAGE1_ANCHOR_TIMESTAMPS", "true")
        response = {
            "id": 7,
            "initial_transcription": TRANSCRIPT.text,
            "timestamped_transcription": TRANSCRIPT.to_storage(),
            "initial_detection_result": {"flagged_snippets": [{"transcription": CLAIM}]},
            "audio_file": AUDIO_FILE,
        }
        with (
            patch("processing_pipeline.stage_1.flows.SupabaseClient") as supabase_cls,
            patch("processing_pipeline.stage_1.flows.genai") as genai,
            patch("processing_pipeline.stage_1.flows.OpenAI"),
            patch("processing_pipeline.stage_1.flows.fetch_kb_context", return_value=None),
        ):
            supabase = supabase_cls.return_value
            supabase.get_active_prompt.return_value = PROMPT_VERSION
            supabase.get_stage_1_llm_response_by_id.return_value = response
            genai.Client.return_value.models.generate_content.return_value.parsed = {
                "flagged_snippets": [{"start_time": "01:00", "end_time": "01:20", "transcription": CLAIM}]
            }
            redo_main_detection([7])

        (_, detection_result), _ = supabase.update_stage_1_llm_response_detection_result.call_args
        assert detection_result["flagged_snippets"][0]["start_time"] == "01:02"
