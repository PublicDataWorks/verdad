import asyncio
import os
from unittest import mock
from unittest.mock import AsyncMock, Mock, call, patch

import pytest
from google.genai import errors
from google.genai.types import FinishReason

from processing_pipeline.constants import GeminiModel, ProcessingStatus
from processing_pipeline.stage_3 import (
    Stage3Executor,
    download_audio_file_from_s3,
    fetch_a_new_snippet_from_supabase,
    fetch_a_specific_snippet_from_supabase,
    get_metadata,
    in_depth_analysis,
    process_snippet,
    update_snippet_in_supabase,
)

SNIPPET_SELECT = (
    "*, audio_file(radio_station_name, radio_station_code, location_state, location_city, recorded_at, "
    'recording_day_of_week), stage_1_llm_response("detection_result")'
)

PROMPT_VERSION = {
    "id": "pv-3",
    "user_prompt": "Analyze this clip.",
    "system_instruction": "system",
    "output_schema": {"type": "object"},
}


class StopLoop(Exception):
    """Raised from a mocked sleep to break out of a repeat=True flow loop"""


class TestStage3:
    @pytest.fixture
    def mock_supabase_client(self):
        with patch("processing_pipeline.stage_3.flows.SupabaseClient") as MockSupabaseClient:
            mock_client = Mock()
            mock_client.get_snippet_by_id.return_value = None
            mock_client.get_a_new_snippet_and_reserve_it.return_value = None
            mock_client.get_active_prompt.return_value = PROMPT_VERSION
            MockSupabaseClient.return_value = mock_client
            yield mock_client

    @pytest.fixture
    def mock_s3_client(self):
        with patch("boto3.client") as mock_boto:
            s3_client = Mock()
            mock_boto.return_value = s3_client
            yield s3_client

    @pytest.fixture
    def mock_gemini_client(self):
        """A genai.Client double: sync files API, async models API"""
        client = Mock()
        uploaded = Mock()
        uploaded.state.name = "PROCESSED"
        uploaded.name = "files/test-audio"
        client.files.upload.return_value = uploaded
        client.files.get.return_value = uploaded
        client.aio.models.generate_content = AsyncMock()
        return client

    @pytest.fixture
    def mock_gemini_response(self):
        """Shape of Stage3Output as consumed by update_snippet_in_supabase"""
        return {
            "transcription": "Test transcription",
            "translation": "Test translation",
            "title": "Test title",
            "summary": "Test summary",
            "explanation": "Test explanation",
            "disinformation_categories": [{"english": "Misinformation", "spanish": "Desinformación"}],
            "keywords_detected": ["keyword1", "keyword2"],
            "language": "es",
            "confidence_scores": {"overall": 96},
            "emotional_tone": "neutral",
            "context": "Test context",
            "political_leaning": "neutral",
        }

    @pytest.fixture
    def analysis_result(self, mock_gemini_response):
        """What Stage3Executor.run_async returns"""
        return {
            "response": mock_gemini_response,
            "grounding_metadata": "test_grounding_metadata",
            "thought_summaries": "test thoughts",
        }

    @pytest.fixture
    def sample_snippet(self):
        return {
            "id": "test-id",
            "file_path": "test/path.mp3",
            "stage_1_llm_response": {
                "detection_result": {
                    "flagged_snippets": [
                        {
                            "uuid": "test-id",
                            "transcription": "Test transcription",
                            "keywords_detected": ["keyword1"],
                            "explanation": "Test explanation",
                            "start_time": "00:00:30",
                            "end_time": "00:01:30",
                        }
                    ]
                }
            },
            "audio_file": {
                "radio_station_name": "Test Station",
                "radio_station_code": "TEST-FM",
                "location_state": "Test State",
                "location_city": "Test City",
                "recorded_at": "2024-01-01T00:00:00Z",
                "recording_day_of_week": "Monday",
            },
            "start_time": "00:00:30",
            "end_time": "00:01:30",
            "duration": "00:01:00",
            "recorded_at": "2024-01-01T00:00:00+00:00",
        }

    # --- tasks ---------------------------------------------------------------

    def test_fetch_specific_snippet(self, mock_supabase_client):
        expected_response = {"id": "test-id", "status": "New"}
        mock_supabase_client.get_snippet_by_id.return_value = expected_response

        assert fetch_a_specific_snippet_from_supabase(mock_supabase_client, "test-id") == expected_response
        mock_supabase_client.get_snippet_by_id.assert_called_once_with(id="test-id", select=SNIPPET_SELECT)

    def test_fetch_specific_snippet_missing(self, mock_supabase_client):
        assert fetch_a_specific_snippet_from_supabase(mock_supabase_client, "missing") is None

    def test_fetch_new_snippet(self, mock_supabase_client):
        expected_response = {"id": "test-id", "status": "New"}
        mock_supabase_client.get_a_new_snippet_and_reserve_it.return_value = expected_response

        assert fetch_a_new_snippet_from_supabase(mock_supabase_client) == expected_response
        mock_supabase_client.get_a_new_snippet_and_reserve_it.assert_called_once()

    def test_download_audio_file(self, mock_s3_client):
        assert download_audio_file_from_s3(mock_s3_client, "test-bucket", "test/path.mp3") == "path.mp3"
        mock_s3_client.download_file.assert_called_once_with("test-bucket", "test/path.mp3", "path.mp3")

    def test_update_snippet(self, mock_supabase_client, mock_gemini_response):
        update_snippet_in_supabase(
            supabase_client=mock_supabase_client,
            snippet_id="test-id",
            gemini_response=mock_gemini_response,
            grounding_metadata="gm",
            thought_summaries="thoughts",
            analyzed_by=GeminiModel.GEMINI_2_5_PRO,
            status=ProcessingStatus.PROCESSED,
            error_message=None,
        )

        mock_supabase_client.update_snippet.assert_called_once_with(
            id="test-id",
            transcription="Test transcription",
            translation="Test translation",
            title="Test title",
            summary="Test summary",
            explanation="Test explanation",
            disinformation_categories=mock_gemini_response["disinformation_categories"],
            keywords_detected=["keyword1", "keyword2"],
            language="es",
            confidence_scores={"overall": 96},
            emotional_tone="neutral",
            context="Test context",
            political_leaning="neutral",
            grounding_metadata="gm",
            thought_summaries="thoughts",
            analyzed_by=GeminiModel.GEMINI_2_5_PRO,
            status=ProcessingStatus.PROCESSED,
            error_message=None,
            stage_3_prompt_version_id=None,
        )

    def test_get_metadata(self, sample_snippet):
        result = get_metadata(sample_snippet)

        assert result["transcription"] == "Test transcription"
        assert result["additional_info"]["time_zone"] == "UTC"
        assert result["additional_info"]["recorded_at"] == "January 1, 2024 12:00 AM"
        assert result["additional_info"]["recording_day_of_week"] == "Monday"
        assert result["start_time"] == "00:30"
        assert result["end_time"] == "01:30"
        assert result["duration"] == "01:00"
        # Fields deliberately withheld from the model for now
        assert "explanation" not in result
        assert "keywords_detected" not in result

    # --- process_snippet -------------------------------------------------------

    def _process(self, supabase_client, snippet, skip_review, gemini_client=None):
        return asyncio.run(
            process_snippet(
                supabase_client=supabase_client,
                gemini_client=gemini_client or Mock(),
                snippet=snippet,
                local_file="test.mp3",
                skip_review=skip_review,
                prompt_version=PROMPT_VERSION,
            )
        )

    def test_process_snippet_high_confidence_goes_to_review(self, mock_supabase_client, sample_snippet, analysis_result):
        gemini_client = Mock()
        with patch(
            "processing_pipeline.stage_3.tasks.Stage3Executor.run_async", new=AsyncMock(return_value=analysis_result)
        ) as mock_run, patch("processing_pipeline.stage_3.tasks.postprocess_snippet") as mock_postprocess:
            self._process(mock_supabase_client, sample_snippet, skip_review=False, gemini_client=gemini_client)

        mock_run.assert_awaited_once_with(
            gemini_client=gemini_client,
            model_name=GeminiModel.GEMINI_2_5_PRO,
            audio_file="test.mp3",
            metadata=mock.ANY,
            prompt_version=PROMPT_VERSION,
        )
        kwargs = mock_supabase_client.update_snippet.call_args.kwargs
        assert kwargs["status"] == ProcessingStatus.READY_FOR_REVIEW
        assert kwargs["analyzed_by"] == GeminiModel.GEMINI_2_5_PRO
        assert kwargs["grounding_metadata"] == "test_grounding_metadata"
        assert kwargs["thought_summaries"] == "test thoughts"
        assert kwargs["stage_3_prompt_version_id"] == "pv-3"
        # Ready-for-review snippets are labelled by stage 4, not here
        mock_postprocess.assert_not_called()

    def test_process_snippet_skip_review(self, mock_supabase_client, sample_snippet, analysis_result):
        with patch(
            "processing_pipeline.stage_3.tasks.Stage3Executor.run_async", new=AsyncMock(return_value=analysis_result)
        ), patch("processing_pipeline.stage_3.tasks.postprocess_snippet") as mock_postprocess:
            self._process(mock_supabase_client, sample_snippet, skip_review=True)

        assert mock_supabase_client.update_snippet.call_args.kwargs["status"] == ProcessingStatus.PROCESSED
        mock_postprocess.assert_called_once_with(
            mock_supabase_client, "test-id", analysis_result["response"]["disinformation_categories"]
        )

    def test_process_snippet_low_confidence_is_processed(self, mock_supabase_client, sample_snippet, analysis_result):
        analysis_result["response"]["confidence_scores"]["overall"] = 50
        with patch(
            "processing_pipeline.stage_3.tasks.Stage3Executor.run_async", new=AsyncMock(return_value=analysis_result)
        ), patch("processing_pipeline.stage_3.tasks.postprocess_snippet") as mock_postprocess:
            self._process(mock_supabase_client, sample_snippet, skip_review=False)

        assert mock_supabase_client.update_snippet.call_args.kwargs["status"] == ProcessingStatus.PROCESSED
        mock_postprocess.assert_called_once()

    def test_process_snippet_no_disinformation_categories(self, mock_supabase_client, sample_snippet, analysis_result):
        analysis_result["response"]["disinformation_categories"] = []
        with patch(
            "processing_pipeline.stage_3.tasks.Stage3Executor.run_async", new=AsyncMock(return_value=analysis_result)
        ), patch("processing_pipeline.stage_3.tasks.postprocess_snippet") as mock_postprocess:
            self._process(mock_supabase_client, sample_snippet, skip_review=True)

        assert mock_supabase_client.update_snippet.call_args.kwargs["disinformation_categories"] == []
        mock_postprocess.assert_called_once_with(mock_supabase_client, "test-id", [])

    def test_process_snippet_falls_back_to_flash_on_server_error(self, mock_supabase_client, sample_snippet, analysis_result):
        server_error = errors.ServerError(503, {"error": {"message": "overloaded", "status": "UNAVAILABLE"}})
        with patch(
            "processing_pipeline.stage_3.tasks.Stage3Executor.run_async",
            new=AsyncMock(side_effect=[server_error, analysis_result]),
        ) as mock_run, patch("processing_pipeline.stage_3.tasks.postprocess_snippet"):
            self._process(mock_supabase_client, sample_snippet, skip_review=True)

        assert mock_run.await_count == 2
        assert mock_run.await_args_list[0].kwargs["model_name"] == GeminiModel.GEMINI_2_5_PRO
        assert mock_run.await_args_list[1].kwargs["model_name"] == GeminiModel.GEMINI_2_5_FLASH
        assert mock_supabase_client.update_snippet.call_args.kwargs["analyzed_by"] == GeminiModel.GEMINI_2_5_FLASH

    def test_process_snippet_auth_error_is_not_retried(self, mock_supabase_client, sample_snippet):
        auth_error = errors.ClientError(401, {"error": {"message": "bad key", "status": "UNAUTHENTICATED"}})
        with patch(
            "processing_pipeline.stage_3.tasks.Stage3Executor.run_async", new=AsyncMock(side_effect=auth_error)
        ) as mock_run:
            self._process(mock_supabase_client, sample_snippet, skip_review=True)

        assert mock_run.await_count == 1
        mock_supabase_client.update_snippet.assert_not_called()
        snippet_id, status, error_message = mock_supabase_client.set_snippet_status.call_args.args
        assert (snippet_id, status) == ("test-id", ProcessingStatus.ERROR)
        assert error_message.startswith("ClientError:")

    def test_process_snippet_error(self, mock_supabase_client, sample_snippet):
        with patch(
            "processing_pipeline.stage_3.tasks.Stage3Executor.run_async", new=AsyncMock(side_effect=RuntimeError("Test error"))
        ):
            self._process(mock_supabase_client, sample_snippet, skip_review=False)

        mock_supabase_client.set_snippet_status.assert_called_once_with(
            "test-id", ProcessingStatus.ERROR, "RuntimeError: Test error"
        )

    def test_process_snippet_invalid_response(self, mock_supabase_client, sample_snippet, mock_gemini_client):
        """Unparseable analysis + failed schema restructuring is recorded as an error on the snippet"""
        analysis_response = Mock(text="not json at all", candidates=[Mock(content=Mock(parts=[]))])
        restructure_response = Mock(parsed=None, candidates=[Mock(finish_reason=FinishReason.STOP)])
        mock_gemini_client.aio.models.generate_content.side_effect = [analysis_response, restructure_response]

        self._process(mock_supabase_client, sample_snippet, skip_review=False, gemini_client=mock_gemini_client)

        snippet_id, status, error_message = mock_supabase_client.set_snippet_status.call_args.args
        assert (snippet_id, status) == ("test-id", ProcessingStatus.ERROR)
        assert "step 2" in error_message
        mock_supabase_client.update_snippet.assert_not_called()

    # --- Stage3Executor ------------------------------------------------------------

    def _run_executor(self, gemini_client, metadata=None):
        return asyncio.run(
            Stage3Executor.run_async(
                gemini_client=gemini_client,
                model_name=GeminiModel.GEMINI_2_5_PRO,
                audio_file="test.mp3",
                metadata=metadata or {"additional_info": {"recorded_at": "January 1, 2024 12:00 AM"}},
                prompt_version=PROMPT_VERSION,
            )
        )

    def test_stage_3_executor_restructures_with_schema(self, mock_gemini_client):
        analysis_response = Mock(text='{"test": "response"}', candidates=[Mock(content=Mock(parts=[]))])
        restructure_response = Mock(parsed={"test": "response", "is_convertible": True})
        mock_gemini_client.aio.models.generate_content.side_effect = [analysis_response, restructure_response]

        result = self._run_executor(mock_gemini_client)

        assert result["response"] == {"test": "response", "is_convertible": True}
        assert result["grounding_metadata"] == "null"  # no verification_evidence in the output
        assert result["thought_summaries"] is None
        assert mock_gemini_client.aio.models.generate_content.await_count == 2
        first_call = mock_gemini_client.aio.models.generate_content.await_args_list[0].kwargs
        assert first_call["model"] == GeminiModel.GEMINI_2_5_PRO
        assert first_call["contents"][0].startswith("Analyze this clip.")
        assert "BREAKING NEWS PROTOCOL" not in first_call["contents"][0]  # recording is years old
        second_call = mock_gemini_client.aio.models.generate_content.await_args_list[1].kwargs
        assert second_call["model"] == GeminiModel.GEMINI_2_5_FLASH
        assert second_call["config"].response_schema is not None
        mock_gemini_client.files.upload.assert_called_once_with(file="test.mp3")
        mock_gemini_client.files.delete.assert_called_once_with(name="files/test-audio")

    def test_stage_3_executor_collects_thoughts(self, mock_gemini_client):
        thought_part = Mock(thought=True, text="thinking...")
        answer_part = Mock(thought=False, text='{"test": "response"}')
        analysis_response = Mock(
            text='{"test": "response"}', candidates=[Mock(content=Mock(parts=[thought_part, answer_part]))]
        )
        restructure_response = Mock(parsed={"test": "response", "is_convertible": True})
        mock_gemini_client.aio.models.generate_content.side_effect = [analysis_response, restructure_response]

        result = self._run_executor(mock_gemini_client)

        assert result["thought_summaries"] == "thinking..."

    def test_stage_3_executor_waits_for_upload_processing(self, mock_gemini_client):
        processing = Mock(name="files/test-audio")
        processing.state.name = "PROCESSING"
        processing.name = "files/test-audio"
        mock_gemini_client.files.upload.return_value = processing
        mock_gemini_client.aio.models.generate_content.side_effect = [
            Mock(text='{"x": 1}', candidates=[Mock(content=Mock(parts=[]))]),
            Mock(parsed={"is_convertible": True}),
        ]

        with patch("processing_pipeline.stage_3.executors.asyncio.sleep", new=AsyncMock()) as mock_sleep:
            self._run_executor(mock_gemini_client)

        mock_sleep.assert_awaited_once_with(1)
        mock_gemini_client.files.get.assert_called_once_with(name="files/test-audio")

    def test_stage_3_executor_max_tokens(self, mock_gemini_client):
        mock_gemini_client.aio.models.generate_content.return_value = Mock(
            text=None, candidates=[Mock(content=Mock(parts=[]), finish_reason=FinishReason.MAX_TOKENS)]
        )

        with pytest.raises(ValueError, match="too long"):
            self._run_executor(mock_gemini_client)

        mock_gemini_client.files.delete.assert_called_once()

    def test_stage_3_executor_not_convertible(self, mock_gemini_client):
        mock_gemini_client.aio.models.generate_content.side_effect = [
            Mock(text="prose", candidates=[Mock(content=Mock(parts=[]))]),
            Mock(parsed={"is_convertible": False}),
        ]

        with pytest.raises(ValueError, match="could not be converted"):
            self._run_executor(mock_gemini_client)

    # --- in_depth_analysis flow ------------------------------------------------------

    @pytest.fixture
    def mock_flow_deps(self):
        with patch("processing_pipeline.stage_3.flows.genai") as mock_genai, patch(
            "processing_pipeline.stage_3.flows.process_snippet", new=AsyncMock()
        ) as mock_process, patch("os.remove") as mock_remove:
            yield {"genai": mock_genai, "process": mock_process, "remove": mock_remove}

    def test_in_depth_analysis_requires_gemini_key(self, mock_supabase_client, mock_s3_client):
        with patch.dict(os.environ, {"GOOGLE_GEMINI_KEY": ""}), pytest.raises(ValueError, match="No Gemini API key set"):
            asyncio.run(in_depth_analysis(snippet_ids=[], skip_review=False, repeat=False))

    def test_in_depth_analysis_flow(self, mock_supabase_client, mock_s3_client, sample_snippet, mock_flow_deps):
        mock_supabase_client.get_a_new_snippet_and_reserve_it.return_value = sample_snippet

        asyncio.run(in_depth_analysis(snippet_ids=None, skip_review=True, repeat=False))

        mock_flow_deps["genai"].Client.assert_called_once_with(api_key="test-key")
        mock_supabase_client.get_active_prompt.assert_called_once()
        mock_supabase_client.get_a_new_snippet_and_reserve_it.assert_called_once()
        mock_s3_client.download_file.assert_called_once_with("test-bucket", "test/path.mp3", "path.mp3")
        mock_flow_deps["process"].assert_awaited_once_with(
            supabase_client=mock_supabase_client,
            gemini_client=mock_flow_deps["genai"].Client.return_value,
            snippet=sample_snippet,
            local_file="path.mp3",
            skip_review=True,
            prompt_version=PROMPT_VERSION,
        )
        mock_flow_deps["remove"].assert_called_once_with("path.mp3")

    def test_in_depth_analysis_with_specific_snippets(
        self, mock_supabase_client, mock_s3_client, sample_snippet, mock_flow_deps
    ):
        mock_supabase_client.get_snippet_by_id.return_value = sample_snippet

        asyncio.run(in_depth_analysis(snippet_ids=["test-id"], skip_review=False, repeat=False))

        mock_supabase_client.get_snippet_by_id.assert_called_once_with(id="test-id", select=SNIPPET_SELECT)
        mock_supabase_client.set_snippet_status.assert_called_once_with("test-id", ProcessingStatus.PROCESSING)
        mock_supabase_client.get_a_new_snippet_and_reserve_it.assert_not_called()
        mock_s3_client.download_file.assert_called_once()
        mock_flow_deps["process"].assert_awaited_once()

    def test_in_depth_analysis_no_snippets(self, mock_supabase_client, mock_s3_client, mock_flow_deps):
        asyncio.run(in_depth_analysis(snippet_ids=["test-id"], skip_review=True, repeat=False))

        mock_s3_client.download_file.assert_not_called()
        mock_flow_deps["process"].assert_not_awaited()

    def test_in_depth_analysis_with_repeat(self, mock_supabase_client, mock_s3_client, sample_snippet, mock_flow_deps):
        mock_supabase_client.get_a_new_snippet_and_reserve_it.side_effect = [sample_snippet, None]
        sleep_calls = []

        async def fake_sleep(seconds):
            sleep_calls.append(seconds)
            if len(sleep_calls) == 2:
                raise StopLoop()

        with patch("processing_pipeline.stage_3.flows.asyncio.sleep", new=fake_sleep), pytest.raises(StopLoop):
            asyncio.run(in_depth_analysis(snippet_ids=None, skip_review=True, repeat=True))

        # Short sleep after processing a snippet, long sleep when the queue is empty
        assert sleep_calls == [2, 60]
        assert mock_supabase_client.get_a_new_snippet_and_reserve_it.call_args_list == [call(), call()]
        mock_flow_deps["process"].assert_awaited_once()
