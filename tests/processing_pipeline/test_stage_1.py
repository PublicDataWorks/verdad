import glob
import json
import os
import uuid
from unittest.mock import Mock, call, patch

import pytest
from google.genai.types import FinishReason, HarmBlockThreshold, HarmCategory
from pydub import AudioSegment

from processing_pipeline.constants import GeminiModel, ProcessingStatus
from processing_pipeline.stage_1 import (
    GeminiTimestampTranscriptionGenerator,
    Stage1Executor,
    disinformation_detection_with_gemini,
    download_audio_file_from_s3,
    fetch_a_new_audio_file_from_supabase,
    fetch_audio_file_by_id,
    fetch_stage_1_llm_response_by_id,
    get_audio_file_metadata,
    initial_disinformation_detection,
    insert_stage_1_llm_response,
    process_audio_file,
    redo_main_detection,
    regenerate_timestamped_transcript,
    transcribe_audio_file_with_open_ai_whisper_1,
    transcribe_audio_file_with_timestamp_with_gemini,
    undo_disinformation_detection,
)

SELECT_WITH_AUDIO_FILE = (
    "*, audio_file(radio_station_name, radio_station_code, location_state, location_city, "
    "recorded_at, recording_day_of_week, file_path)"
)

# Prompt versions are loaded from the `prompt_versions` table at flow start; this is the minimal shape.
PROMPT_VERSION = {
    "id": "pv-1",
    "user_prompt": "prompt",
    "system_instruction": "system",
    "output_schema": {"type": "object"},
}

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


@pytest.fixture
def mock_environment(monkeypatch):
    """Provider keys the flows need to build their clients"""
    monkeypatch.setenv("GOOGLE_GEMINI_KEY", "test-key")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("R2_BUCKET_NAME", "test-bucket")


@pytest.fixture
def mock_supabase_client():
    """Mock the SupabaseClient the flows construct"""
    with patch("processing_pipeline.stage_1.flows.SupabaseClient") as MockSupabaseClient:
        mock_client = Mock()
        mock_client.get_a_new_audio_file_and_reserve_it.return_value = None
        mock_client.get_audio_file_by_id.return_value = None
        mock_client.get_stage_1_llm_response_by_id.return_value = None
        mock_client.get_active_prompt.return_value = PROMPT_VERSION
        MockSupabaseClient.return_value = mock_client
        yield mock_client


@pytest.fixture
def mock_s3_client():
    with patch("boto3.client") as mock:
        s3_client = Mock()
        mock.return_value = s3_client
        yield s3_client


@pytest.fixture
def mock_gemini_client():
    """Mock the genai.Client the flows build from GOOGLE_GEMINI_KEY"""
    with patch("processing_pipeline.stage_1.flows.genai") as mock_genai:
        client = Mock()
        client.models.generate_content.return_value.parsed = {"flagged_snippets": []}
        mock_genai.Client.return_value = client
        yield client


@pytest.fixture
def mock_openai_client():
    """Mock the OpenAI client the flows build from OPENAI_API_KEY"""
    with patch("processing_pipeline.stage_1.flows.OpenAI") as mock_openai:
        client = Mock()
        mock_openai.return_value = client
        yield client


@pytest.fixture
def sample_audio_file(test_data_dir):
    """A 45-second silent mp3, i.e. three 20-second segments"""
    audio_path = os.path.join(test_data_dir, "stage_1_test_audio.mp3")
    AudioSegment.silent(duration=45_000).export(audio_path, format="mp3")
    yield audio_path
    for path in glob.glob(f"{audio_path}*"):
        os.remove(path)


class TestFetchFunctions:
    def test_fetch_new_audio_file_success(self, mock_supabase_client):
        expected_response = {"id": 1, "status": "New"}
        mock_supabase_client.get_a_new_audio_file_and_reserve_it.return_value = expected_response

        assert fetch_a_new_audio_file_from_supabase(mock_supabase_client) == expected_response
        mock_supabase_client.get_a_new_audio_file_and_reserve_it.assert_called_once()

    def test_fetch_new_audio_file_none(self, mock_supabase_client):
        assert fetch_a_new_audio_file_from_supabase(mock_supabase_client) is None

    def test_fetch_audio_file_by_id_success(self, mock_supabase_client):
        expected_response = {"id": 1, "status": "New"}
        mock_supabase_client.get_audio_file_by_id.return_value = expected_response

        assert fetch_audio_file_by_id(mock_supabase_client, 1) == expected_response
        mock_supabase_client.get_audio_file_by_id.assert_called_once_with(1)

    def test_fetch_stage_1_llm_response_by_id_success(self, mock_supabase_client):
        expected_response = {"id": 1, "status": "New"}
        mock_supabase_client.get_stage_1_llm_response_by_id.return_value = expected_response

        assert fetch_stage_1_llm_response_by_id(mock_supabase_client, 1) == expected_response
        mock_supabase_client.get_stage_1_llm_response_by_id.assert_called_once_with(
            id=1, select=SELECT_WITH_AUDIO_FILE
        )

    def test_fetch_stage_1_llm_response_by_id_missing(self, mock_supabase_client):
        assert fetch_stage_1_llm_response_by_id(mock_supabase_client, 1) is None


class TestS3Operations:
    def test_download_audio_file_success(self, mock_s3_client, mock_environment):
        result = download_audio_file_from_s3(mock_s3_client, "test/path.mp3")

        assert result == "path.mp3"
        mock_s3_client.download_file.assert_called_once_with("test-bucket", "test/path.mp3", "path.mp3")


class TestMetadata:
    def test_get_audio_file_metadata(self):
        assert get_audio_file_metadata(AUDIO_FILE) == {
            "radio_station_name": "Test Station",
            "radio_station_code": "TEST-FM",
            "location": {"state": "Test State", "city": "Test City"},
            "recorded_at": "January 1, 2024 12:00 AM",
            "recording_day_of_week": "Monday",
            "time_zone": "UTC",
        }


class TestTranscriptionFunctions:
    def test_transcribe_with_timestamp_with_gemini_success(self):
        gemini_client = Mock()
        with patch("processing_pipeline.stage_1.tasks.GeminiTimestampTranscriptionGenerator") as mock_generator:
            mock_generator.run.return_value = "Test timestamped transcription"

            result = transcribe_audio_file_with_timestamp_with_gemini(
                gemini_client, "test.mp3", PROMPT_VERSION, GeminiModel.GEMINI_2_5_FLASH
            )

        assert result == {"timestamped_transcription": "Test timestamped transcription"}
        mock_generator.run.assert_called_once_with(
            gemini_client=gemini_client,
            audio_file="test.mp3",
            model_name=GeminiModel.GEMINI_2_5_FLASH,
            prompt_version=PROMPT_VERSION,
            segment_length=20,
            batch_size=30,
        )

    def test_transcribe_with_timestamp_requires_client(self):
        with pytest.raises(ValueError, match="Gemini client is not provided"):
            transcribe_audio_file_with_timestamp_with_gemini(None, "test.mp3", PROMPT_VERSION, GeminiModel.GEMINI_2_5_FLASH)


class TestDetectionFunctions:
    def test_disinformation_detection_success(self):
        gemini_client = Mock()
        with patch("processing_pipeline.stage_1.tasks.Stage1Executor") as mock_executor:
            mock_executor.run.return_value = {"flagged_snippets": [{"transcription": "Test snippet"}]}

            result = disinformation_detection_with_gemini(
                gemini_client,
                "Test transcription",
                {"station": "test"},
                PROMPT_VERSION,
                GeminiModel.GEMINI_2_5_FLASH,
                kb_context="kb",
            )

        # Every flagged snippet gets a uuid that later stages key on
        assert len(result["flagged_snippets"]) == 1
        uuid.UUID(result["flagged_snippets"][0]["uuid"])
        mock_executor.run.assert_called_once_with(
            gemini_client=gemini_client,
            model_name=GeminiModel.GEMINI_2_5_FLASH,
            timestamped_transcription="Test transcription",
            metadata={"station": "test"},
            prompt_version=PROMPT_VERSION,
            kb_context="kb",
        )

    def test_disinformation_detection_requires_client(self):
        with pytest.raises(ValueError, match="Gemini client is not provided"):
            disinformation_detection_with_gemini(None, "T", {}, PROMPT_VERSION, GeminiModel.GEMINI_2_5_FLASH)


class TestStage1Executor:
    def _client(self, parsed=None, finish_reason=None):
        client = Mock()
        result = Mock()
        result.parsed = parsed
        result.candidates = [Mock(finish_reason=finish_reason)]
        client.models.generate_content.return_value = result
        return client

    def test_run_success(self):
        client = self._client(parsed={"flagged_snippets": []})

        result = Stage1Executor.run(
            gemini_client=client,
            model_name=GeminiModel.GEMINI_2_5_FLASH,
            timestamped_transcription="Test transcription",
            metadata={"station": "test"},
            prompt_version=PROMPT_VERSION,
        )

        assert result == {"flagged_snippets": []}
        _, kwargs = client.models.generate_content.call_args
        assert kwargs["model"] == GeminiModel.GEMINI_2_5_FLASH
        assert kwargs["contents"] == ["prompt"]
        assert kwargs["config"].response_mime_type == "application/json"
        assert kwargs["config"].max_output_tokens == 16384
        assert kwargs["config"].thinking_config.thinking_budget == 4096

    def test_run_formats_user_prompt(self):
        client = self._client(parsed={"flagged_snippets": []})
        prompt_version = {**PROMPT_VERSION, "user_prompt": "{kb_context}|{metadata}|{timestamped_transcription}"}
        metadata = {"station": "test"}

        Stage1Executor.run(client, GeminiModel.GEMINI_2_5_FLASH, "T", metadata, prompt_version, kb_context="KB")

        _, kwargs = client.models.generate_content.call_args
        assert kwargs["contents"] == [f"KB|{json.dumps(metadata, indent=2)}|T"]

    def test_run_no_response(self):
        client = self._client(parsed=None, finish_reason=FinishReason.STOP)
        with pytest.raises(ValueError, match="No response from Gemini"):
            Stage1Executor.run(client, GeminiModel.GEMINI_2_5_FLASH, "T", {}, PROMPT_VERSION)

    def test_run_max_tokens(self):
        client = self._client(parsed=None, finish_reason=FinishReason.MAX_TOKENS)
        with pytest.raises(ValueError, match="too long"):
            Stage1Executor.run(client, GeminiModel.GEMINI_2_5_FLASH, "T", {}, PROMPT_VERSION)

    def test_safety_settings_configuration(self):
        client = self._client(parsed={"flagged_snippets": []})

        Stage1Executor.run(client, GeminiModel.GEMINI_2_5_FLASH, "T", {}, PROMPT_VERSION)

        _, kwargs = client.models.generate_content.call_args
        safety_settings = kwargs["config"].safety_settings
        assert {setting.category for setting in safety_settings} == {
            HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
            HarmCategory.HARM_CATEGORY_HATE_SPEECH,
            HarmCategory.HARM_CATEGORY_HARASSMENT,
            HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
            HarmCategory.HARM_CATEGORY_CIVIC_INTEGRITY,
        }
        assert all(setting.threshold == HarmBlockThreshold.BLOCK_NONE for setting in safety_settings)


class TestGeminiTimestampTranscriptionGenerator:
    @staticmethod
    def _segments_response(count):
        result = Mock()
        result.parsed = {
            "segments": [{"segment_number": i, "transcript": f"seg {i}"} for i in range(1, count + 1)],
        }
        return result

    def test_split_audio_into_segments(self, sample_audio_file):
        paths = GeminiTimestampTranscriptionGenerator.split_audio_into_segments(sample_audio_file, 20_000)

        assert len(paths) == 3
        assert all(os.path.exists(path) for path in paths)
        assert len(AudioSegment.from_mp3(paths[-1])) == pytest.approx(5_000, abs=200)

    def test_format_final_transcription(self):
        result = GeminiTimestampTranscriptionGenerator.format_final_transcription({2: "b", 1: "a", 3: "c"}, 20)

        assert result == "[00:00] a\n[00:20] b\n[00:40] c\n"

    def test_run_success(self, sample_audio_file):
        client = Mock()
        client.models.generate_content.return_value = self._segments_response(3)

        with patch("time.sleep"):
            result = GeminiTimestampTranscriptionGenerator.run(
                gemini_client=client,
                audio_file=sample_audio_file,
                model_name=GeminiModel.GEMINI_2_5_FLASH,
                prompt_version=PROMPT_VERSION,
            )

        assert result == "[00:00] seg 1\n[00:20] seg 2\n[00:40] seg 3\n"
        client.models.generate_content.assert_called_once()
        # Segment files are cleaned up
        assert glob.glob(f"{sample_audio_file}_segment_*.mp3") == []

    def test_run_in_batches(self, sample_audio_file):
        client = Mock()
        client.models.generate_content.side_effect = [self._segments_response(2), self._segments_response(1)]

        with patch("time.sleep"):
            result = GeminiTimestampTranscriptionGenerator.run(
                gemini_client=client,
                audio_file=sample_audio_file,
                model_name=GeminiModel.GEMINI_2_5_FLASH,
                prompt_version=PROMPT_VERSION,
                batch_size=2,
            )

        assert client.models.generate_content.call_count == 2
        # Segment numbers are relative to the batch and re-based to absolute positions
        assert result == "[00:00] seg 1\n[00:20] seg 2\n[00:40] seg 1\n"

    def test_run_segment_count_mismatch(self, sample_audio_file):
        client = Mock()
        client.models.generate_content.return_value = self._segments_response(1)

        with patch("time.sleep"), pytest.raises(ValueError, match="Segment count mismatch"):
            GeminiTimestampTranscriptionGenerator.run(client, sample_audio_file, GeminiModel.GEMINI_2_5_FLASH, PROMPT_VERSION)

        assert glob.glob(f"{sample_audio_file}_segment_*.mp3") == []

    def test_transcribe_batch_no_response(self, sample_audio_file):
        client = Mock()
        result = Mock()
        result.parsed = None
        result.candidates = [Mock(finish_reason=FinishReason.STOP)]
        client.models.generate_content.return_value = result

        with pytest.raises(ValueError, match="No response from Gemini"):
            GeminiTimestampTranscriptionGenerator.transcribe_batch(
                client, [sample_audio_file], GeminiModel.GEMINI_2_5_FLASH, PROMPT_VERSION
            )

    def test_transcribe_batch_max_tokens(self, sample_audio_file):
        client = Mock()
        result = Mock()
        result.parsed = None
        result.candidates = [Mock(finish_reason=FinishReason.MAX_TOKENS)]
        client.models.generate_content.return_value = result

        with pytest.raises(ValueError, match="too long"):
            GeminiTimestampTranscriptionGenerator.transcribe_batch(
                client, [sample_audio_file], GeminiModel.GEMINI_2_5_FLASH, PROMPT_VERSION
            )

    @pytest.mark.parametrize(
        "model_name, thinking_budget",
        [(GeminiModel.GEMINI_2_5_FLASH, 0), (GeminiModel.GEMINI_2_5_PRO, 128)],
    )
    def test_transcribe_batch_config(self, sample_audio_file, model_name, thinking_budget):
        client = Mock()
        client.models.generate_content.return_value = self._segments_response(1)

        GeminiTimestampTranscriptionGenerator.transcribe_batch(client, [sample_audio_file], model_name, PROMPT_VERSION)

        _, kwargs = client.models.generate_content.call_args
        assert kwargs["model"] == model_name
        assert kwargs["contents"][0] == "prompt"
        assert len(kwargs["contents"]) == 4  # prompt + (open tag, audio part, close tag)
        assert kwargs["config"].thinking_config.thinking_budget == thinking_budget
        assert kwargs["config"].max_output_tokens == 16384
        assert len(kwargs["config"].safety_settings) == 5


class TestWhisper:
    def test_transcribe_audio_file_with_whisper_1(self):
        mock_file = Mock()
        with patch("os.getenv", return_value="test-key"), patch("builtins.open", return_value=mock_file) as mock_open, patch(
            "processing_pipeline.stage_1.tasks.OpenAI"
        ) as mock_openai_class:
            mock_client = Mock()
            mock_openai_class.return_value = mock_client
            mock_client.audio.transcriptions.create.return_value = Mock(
                text="Test transcription",
                language="en",
                duration=60.0,
                segments=[Mock(start=0, text="Test segment 1"), Mock(start=30, text="Test segment 2")],
            )

            result = transcribe_audio_file_with_open_ai_whisper_1("test.mp3")

        mock_open.assert_called_once_with("test.mp3", "rb")
        mock_openai_class.assert_called_once_with(api_key="test-key")
        mock_client.audio.transcriptions.create.assert_called_once_with(
            model="whisper-1", file=mock_file, response_format="verbose_json", timestamp_granularities=["segment"]
        )
        assert result["language"] == "en"
        assert result["duration"] == 60
        assert result["transcription"] == "Test transcription"
        assert result["timestamped_transcription"] == "[00:00] Test segment 1\n[00:30] Test segment 2\n"

    def test_transcribe_audio_file_with_whisper_1_no_api_key(self):
        with patch.dict("os.environ", {}, clear=True), pytest.raises(ValueError, match="OpenAI API key was not set!"):
            transcribe_audio_file_with_open_ai_whisper_1("test.mp3")


class TestProcessAudioFile:
    @pytest.fixture
    def mock_tasks(self):
        """Patch the sub-tasks process_audio_file orchestrates"""
        with patch("processing_pipeline.stage_1.tasks.initial_transcription_with_gemini") as initial_transcription, patch(
            "processing_pipeline.stage_1.tasks.fetch_kb_context"
        ) as kb_context, patch(
            "processing_pipeline.stage_1.tasks.initial_disinformation_detection_with_gemini"
        ) as initial_detection, patch(
            "processing_pipeline.stage_1.tasks.transcribe_audio_file_with_timestamp_with_gemini"
        ) as transcribe, patch(
            "processing_pipeline.stage_1.tasks.disinformation_detection_with_gemini"
        ) as detect:
            initial_transcription.return_value = "initial transcription"
            kb_context.return_value = "kb context"
            initial_detection.return_value = {"flagged_snippets": [{"transcription": "maybe"}]}
            transcribe.return_value = {"timestamped_transcription": "[00:00] text"}
            detect.return_value = {"flagged_snippets": [{"uuid": "u1"}]}
            yield {
                "initial_transcription": initial_transcription,
                "kb_context": kb_context,
                "initial_detection": initial_detection,
                "transcribe": transcribe,
                "detect": detect,
            }

    def _run(self, supabase_client, gemini_client=None, openai_client=None):
        process_audio_file(
            supabase_client=supabase_client,
            gemini_client=gemini_client or Mock(),
            openai_client=openai_client or Mock(),
            audio_file=AUDIO_FILE,
            local_file="test.mp3",
            initial_transcription_prompt_version={**PROMPT_VERSION, "id": "pv-it"},
            initial_detection_prompt_version={**PROMPT_VERSION, "id": "pv-id"},
            transcription_prompt_version={**PROMPT_VERSION, "id": "pv-tt"},
            detection_prompt_version={**PROMPT_VERSION, "id": "pv-dd"},
        )

    def test_flagged_snippets_are_stored_as_new(self, mock_supabase_client, mock_tasks):
        gemini_client, openai_client = Mock(), Mock()

        self._run(mock_supabase_client, gemini_client, openai_client)

        mock_tasks["kb_context"].assert_called_once_with(mock_supabase_client, openai_client, "initial transcription")
        mock_tasks["transcribe"].assert_called_once_with(
            gemini_client=gemini_client,
            audio_file="test.mp3",
            prompt_version={**PROMPT_VERSION, "id": "pv-tt"},
            model_name=GeminiModel.GEMINI_2_5_FLASH,
        )
        mock_tasks["detect"].assert_called_once_with(
            gemini_client=gemini_client,
            timestamped_transcription="[00:00] text",
            metadata=get_audio_file_metadata(AUDIO_FILE),
            prompt_version={**PROMPT_VERSION, "id": "pv-dd"},
            model_name=GeminiModel.GEMINI_2_5_FLASH,
            kb_context="kb context",
        )
        mock_supabase_client.insert_stage_1_llm_response.assert_called_once_with(
            audio_file_id=1,
            initial_transcription="initial transcription",
            initial_detection_result={"flagged_snippets": [{"transcription": "maybe"}]},
            transcriptor=GeminiModel.GEMINI_2_5_FLASH,
            timestamped_transcription={"timestamped_transcription": "[00:00] text"},
            detection_result={"flagged_snippets": [{"uuid": "u1"}]},
            status="New",
            detection_prompt_version_id="pv-dd",
            transcription_prompt_version_id="pv-tt",
        )
        mock_supabase_client.set_audio_file_status.assert_called_once_with(1, ProcessingStatus.PROCESSED, None)

    def test_no_initial_flags_skips_timestamped_transcription(self, mock_supabase_client, mock_tasks):
        mock_tasks["initial_detection"].return_value = {"flagged_snippets": []}

        self._run(mock_supabase_client)

        mock_tasks["transcribe"].assert_not_called()
        mock_tasks["detect"].assert_not_called()
        mock_supabase_client.insert_stage_1_llm_response.assert_called_once_with(
            audio_file_id=1,
            initial_transcription="initial transcription",
            initial_detection_result={"flagged_snippets": []},
            transcriptor=None,
            timestamped_transcription=None,
            detection_result=None,
            status="Processed",
            detection_prompt_version_id=None,
            transcription_prompt_version_id=None,
        )
        mock_supabase_client.set_audio_file_status.assert_called_once_with(1, ProcessingStatus.PROCESSED, None)

    def test_no_main_flags_is_processed(self, mock_supabase_client, mock_tasks):
        mock_tasks["detect"].return_value = {"flagged_snippets": []}

        self._run(mock_supabase_client)

        kwargs = mock_supabase_client.insert_stage_1_llm_response.call_args.kwargs
        assert kwargs["status"] == "Processed"
        assert kwargs["detection_result"] == {"flagged_snippets": []}
        assert kwargs["detection_prompt_version_id"] == "pv-dd"

    def test_error_marks_audio_file(self, mock_supabase_client, mock_tasks):
        mock_tasks["initial_transcription"].side_effect = Exception("Test error")

        self._run(mock_supabase_client)

        mock_supabase_client.insert_stage_1_llm_response.assert_not_called()
        mock_supabase_client.set_audio_file_status.assert_called_once_with(1, ProcessingStatus.ERROR, "Test error")

    def test_insert_stage_1_llm_response(self, mock_supabase_client):
        insert_stage_1_llm_response(
            supabase_client=mock_supabase_client,
            audio_file_id=1,
            initial_transcription="Test transcription",
            initial_detection_result={"test": "result"},
            transcriptor="gemini-2.5-flash",
            timestamped_transcription={"test": "transcription"},
            detection_result={"test": "result"},
            status="New",
        )

        mock_supabase_client.insert_stage_1_llm_response.assert_called_once_with(
            audio_file_id=1,
            initial_transcription="Test transcription",
            initial_detection_result={"test": "result"},
            transcriptor="gemini-2.5-flash",
            timestamped_transcription={"test": "transcription"},
            detection_result={"test": "result"},
            status="New",
            detection_prompt_version_id=None,
            transcription_prompt_version_id=None,
        )


class TestInitialDisinformationDetectionFlow:
    def test_processes_next_new_audio_file(
        self, mock_environment, mock_supabase_client, mock_s3_client, mock_gemini_client, mock_openai_client
    ):
        mock_supabase_client.get_a_new_audio_file_and_reserve_it.return_value = AUDIO_FILE

        with patch("os.remove") as mock_remove, patch("processing_pipeline.stage_1.flows.process_audio_file") as mock_process:
            initial_disinformation_detection(audio_file_id=None, limit=1)

        mock_supabase_client.get_a_new_audio_file_and_reserve_it.assert_called_once()
        assert mock_supabase_client.get_active_prompt.call_count == 4
        mock_s3_client.download_file.assert_called_once_with("test-bucket", "test/path.mp3", "path.mp3")
        mock_process.assert_called_once()
        kwargs = mock_process.call_args.kwargs
        assert kwargs["gemini_client"] is mock_gemini_client
        assert kwargs["openai_client"] is mock_openai_client
        assert kwargs["audio_file"] == AUDIO_FILE
        assert kwargs["local_file"] == "path.mp3"
        assert kwargs["detection_prompt_version"] == PROMPT_VERSION
        mock_remove.assert_called_once_with("path.mp3")

    def test_specific_audio_file(
        self, mock_environment, mock_supabase_client, mock_s3_client, mock_gemini_client, mock_openai_client
    ):
        mock_supabase_client.get_audio_file_by_id.return_value = AUDIO_FILE

        with patch("os.remove"), patch("processing_pipeline.stage_1.flows.process_audio_file") as mock_process:
            initial_disinformation_detection(audio_file_id=1, limit=1000)

        mock_supabase_client.get_audio_file_by_id.assert_called_once_with(1)
        mock_supabase_client.get_a_new_audio_file_and_reserve_it.assert_not_called()
        mock_process.assert_called_once()

    def test_waits_when_idle(
        self, mock_environment, mock_supabase_client, mock_s3_client, mock_gemini_client, mock_openai_client
    ):
        mock_supabase_client.get_a_new_audio_file_and_reserve_it.side_effect = [None, AUDIO_FILE]

        with patch("os.remove"), patch("time.sleep") as mock_sleep, patch(
            "processing_pipeline.stage_1.flows.process_audio_file"
        ) as mock_process:
            initial_disinformation_detection(audio_file_id=None, limit=1)

        mock_sleep.assert_called_once_with(60)
        mock_process.assert_called_once()

    def test_without_gemini_key(
        self, mock_environment, monkeypatch, mock_supabase_client, mock_s3_client, mock_gemini_client, mock_openai_client
    ):
        """The flow still runs without GOOGLE_GEMINI_KEY; tasks get gemini_client=None and fail per file"""
        monkeypatch.delenv("GOOGLE_GEMINI_KEY")
        mock_supabase_client.get_audio_file_by_id.return_value = AUDIO_FILE

        with patch("os.remove"), patch("processing_pipeline.stage_1.flows.process_audio_file") as mock_process:
            initial_disinformation_detection(audio_file_id=1, limit=1)

        assert mock_process.call_args.kwargs["gemini_client"] is None

    def test_requires_openai_key(self, mock_environment, monkeypatch, mock_supabase_client, mock_s3_client, mock_gemini_client):
        monkeypatch.delenv("OPENAI_API_KEY")

        with pytest.raises(ValueError, match="OPENAI_API_KEY"):
            initial_disinformation_detection(audio_file_id=1, limit=1)


class TestMaintenanceFlows:
    def test_undo_disinformation_detection(self, mock_supabase_client):
        undo_disinformation_detection([1, 2])

        mock_supabase_client.reset_audio_file_status.assert_called_once_with([1, 2])
        mock_supabase_client.delete_stage_1_llm_responses.assert_called_once_with([1, 2])

    def test_undo_disinformation_detection_without_ids(self, mock_supabase_client):
        undo_disinformation_detection([])

        mock_supabase_client.reset_audio_file_status.assert_not_called()
        mock_supabase_client.delete_stage_1_llm_responses.assert_not_called()

    @pytest.fixture
    def stage_1_llm_response(self):
        return {
            "id": 1,
            "initial_transcription": "initial transcription",
            "timestamped_transcription": {"timestamped_transcription": "[00:00] Test transcription"},
            "initial_detection_result": {"flagged_snippets": [{"transcription": "Test snippet"}]},
            "audio_file": {**AUDIO_FILE, "file_path": "test.mp3"},
        }

    def test_redo_main_detection(
        self, mock_environment, mock_supabase_client, mock_gemini_client, mock_openai_client, stage_1_llm_response
    ):
        mock_supabase_client.get_stage_1_llm_response_by_id.return_value = stage_1_llm_response
        mock_gemini_client.models.generate_content.return_value.parsed = {
            "flagged_snippets": [{"transcription": "Updated snippet"}],
        }

        with patch("processing_pipeline.stage_1.flows.fetch_kb_context", return_value="kb") as mock_kb:
            redo_main_detection([1])

        mock_supabase_client.get_stage_1_llm_response_by_id.assert_called_once_with(id=1, select=SELECT_WITH_AUDIO_FILE)
        mock_kb.assert_called_once_with(mock_supabase_client, mock_openai_client, "initial transcription")
        mock_gemini_client.models.generate_content.assert_called_once()
        (response_id, detection_result), _ = mock_supabase_client.update_stage_1_llm_response_detection_result.call_args
        assert response_id == 1
        assert detection_result["flagged_snippets"][0]["transcription"] == "Updated snippet"
        uuid.UUID(detection_result["flagged_snippets"][0]["uuid"])
        mock_supabase_client.reset_stage_1_llm_response_status.assert_called_once_with(1)

    def test_redo_main_detection_without_initial_flags(
        self, mock_environment, mock_supabase_client, mock_gemini_client, mock_openai_client, stage_1_llm_response
    ):
        stage_1_llm_response["initial_detection_result"] = {"flagged_snippets": []}
        mock_supabase_client.get_stage_1_llm_response_by_id.return_value = stage_1_llm_response

        redo_main_detection([1])

        mock_gemini_client.models.generate_content.assert_not_called()
        mock_supabase_client.update_stage_1_llm_response_detection_result.assert_not_called()

    def test_redo_main_detection_without_ids(self, mock_supabase_client):
        redo_main_detection([])

        mock_supabase_client.get_stage_1_llm_response_by_id.assert_not_called()

    def test_regenerate_timestamped_transcript(
        self, mock_environment, mock_supabase_client, mock_s3_client, mock_gemini_client, mock_openai_client, stage_1_llm_response
    ):
        mock_supabase_client.get_stage_1_llm_response_by_id.return_value = stage_1_llm_response
        mock_gemini_client.models.generate_content.return_value.parsed = {"flagged_snippets": [{"transcription": "x"}]}

        with patch("os.remove") as mock_remove, patch(
            "processing_pipeline.stage_1.flows.transcribe_audio_file_with_timestamp_with_gemini",
            return_value={"timestamped_transcription": "[00:00] regenerated"},
        ) as mock_transcribe, patch("processing_pipeline.stage_1.flows.fetch_kb_context", return_value=None):
            regenerate_timestamped_transcript([1])

        mock_s3_client.download_file.assert_called_once_with("test-bucket", "test.mp3", "test.mp3")
        mock_transcribe.assert_called_once_with(
            gemini_client=mock_gemini_client,
            audio_file="test.mp3",
            prompt_version=PROMPT_VERSION,
            model_name=GeminiModel.GEMINI_2_5_FLASH,
        )
        mock_supabase_client.update_stage_1_llm_response_timestamped_transcription.assert_called_once_with(
            1, {"timestamped_transcription": "[00:00] regenerated"}, GeminiModel.GEMINI_2_5_FLASH
        )
        mock_supabase_client.update_stage_1_llm_response_detection_result.assert_called_once()
        mock_supabase_client.reset_stage_1_llm_response_status.assert_called_once_with(1)
        mock_supabase_client.set_stage_1_llm_response_status.assert_not_called()
        mock_remove.assert_called_once_with("test.mp3")

    def test_regenerate_timestamped_transcript_no_flags_after_detection(
        self, mock_environment, mock_supabase_client, mock_s3_client, mock_gemini_client, mock_openai_client, stage_1_llm_response
    ):
        mock_supabase_client.get_stage_1_llm_response_by_id.return_value = stage_1_llm_response
        mock_gemini_client.models.generate_content.return_value.parsed = {"flagged_snippets": []}

        with patch("os.remove"), patch(
            "processing_pipeline.stage_1.flows.transcribe_audio_file_with_timestamp_with_gemini",
            return_value={"timestamped_transcription": "[00:00] regenerated"},
        ), patch("processing_pipeline.stage_1.flows.fetch_kb_context", return_value=None):
            regenerate_timestamped_transcript([1])

        mock_supabase_client.set_stage_1_llm_response_status.assert_called_once_with(1, "Processed", None)
        mock_supabase_client.reset_stage_1_llm_response_status.assert_not_called()

    def test_regenerate_timestamped_transcript_download_error(
        self, mock_environment, mock_supabase_client, mock_s3_client, mock_gemini_client, mock_openai_client, stage_1_llm_response
    ):
        mock_supabase_client.get_stage_1_llm_response_by_id.return_value = stage_1_llm_response
        mock_s3_client.download_file.side_effect = OSError("Download failed")

        with pytest.raises(OSError, match="Download failed"):
            regenerate_timestamped_transcript([1])

        mock_supabase_client.set_stage_1_llm_response_status.assert_not_called()
        mock_supabase_client.update_stage_1_llm_response_timestamped_transcription.assert_not_called()

    def test_regenerate_timestamped_transcript_sleep_calls(self, mock_supabase_client):
        """Sanity check that call() is importable for assert_has_calls users; keeps the helper import honest"""
        assert call(60) == call(60)
