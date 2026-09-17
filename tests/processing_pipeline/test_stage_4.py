import asyncio
import json
import os
from unittest import mock
from unittest.mock import AsyncMock, Mock, call, patch

import pytest
from google.genai import errors

from processing_pipeline.constants import GeminiModel
from processing_pipeline.stage_4 import (
    Stage4Executor,
    analysis_review,
    fetch_a_ready_for_review_snippet_from_supabase,
    fetch_a_specific_snippet_from_supabase,
    prepare_snippet_for_review,
    process_snippet,
    submit_snippet_review_result,
)
from processing_pipeline.stage_4.constants import Stage4SubStage

PROMPT_VERSIONS = {
    sub_stage.value: {"id": f"pv-{sub_stage.value}", "system_instruction": f"{sub_stage.value} instructions"}
    for sub_stage in Stage4SubStage
}


class StopLoop(Exception):
    """Raised from a mocked sleep to break out of a repeat=True flow loop"""


class TestStage4:
    @pytest.fixture
    def mock_supabase_client(self):
        with patch("processing_pipeline.stage_4.flows.SupabaseClient") as MockSupabaseClient:
            mock_client = Mock()
            mock_client.get_snippet_by_id.return_value = None
            mock_client.get_a_ready_for_review_snippet_and_reserve_it.return_value = None
            mock_client.get_audio_file_by_id.return_value = {
                "location_city": "Test City",
                "location_state": "Test State",
                "radio_station_code": "TEST-FM",
                "radio_station_name": "Test Station",
            }
            mock_client.get_active_prompt.side_effect = lambda stage, sub_stage: PROMPT_VERSIONS[sub_stage.value]
            MockSupabaseClient.return_value = mock_client
            yield mock_client

    @pytest.fixture
    def sample_snippet(self):
        """A stage-3 processed snippet as stored in `snippets`"""
        return {
            "id": "test-id",
            "transcription": "Test transcription",
            "translation": "Test translation",
            "title": {"english": "Test title", "spanish": "Título de prueba"},
            "summary": {"english": "Test summary", "spanish": "Resumen de prueba"},
            "explanation": {"english": "Test explanation", "spanish": "Explicación de prueba"},
            "disinformation_categories": [{"english": "Category 1", "spanish": "Categoría 1"}],
            "keywords_detected": ["keyword1", "keyword2"],
            "language": {"primary_language": "es", "dialect": "standard", "register": "formal"},
            "confidence_scores": {"overall": 90},
            "context": {"before": "Test before", "main": "Test main", "after": "Test after"},
            "political_leaning": {"score": 0.0},
            "recorded_at": "2024-01-01T00:00:00+00:00",
            "audio_file": "test-audio-file-id",
            "previous_analysis": None,
        }

    @pytest.fixture
    def review_result(self):
        """What the reviewer agent produces"""
        return {
            "translation": "Reviewed translation",
            "title": {"english": "Reviewed title", "spanish": "Título revisado"},
            "summary": {"english": "Reviewed summary", "spanish": "Resumen revisado"},
            "explanation": {"english": "Reviewed explanation", "spanish": "Explicación revisada"},
            "disinformation_categories": [{"english": "Category 2", "spanish": "Categoría 2"}],
            "keywords_detected": ["keyword3"],
            "language": {"primary_language": "es", "dialect": "standard", "register": "formal"},
            "confidence_scores": {"overall": 40},
            "political_leaning": {"score": 0.1},
            "thought_summaries": "reviewer thoughts",
        }

    # --- tasks ---------------------------------------------------------------

    def test_prepare_snippet_for_review(self, mock_supabase_client, sample_snippet):
        prepared = prepare_snippet_for_review(mock_supabase_client, sample_snippet)

        mock_supabase_client.get_audio_file_by_id.assert_called_once_with(
            "test-audio-file-id", select="location_city,location_state,radio_station_code,radio_station_name"
        )
        assert prepared["transcription"] == "Test transcription"
        assert prepared["disinformation_snippet"] == "Test main"
        assert prepared["recorded_at"] == "2024-01-01T00:00:00+00:00"
        assert prepared["metadata"] == {
            "recorded_at": "January 1, 2024 12:00 AM",
            "recording_day_of_week": "Monday",
            "location_city": "Test City",
            "location_state": "Test State",
            "radio_station_code": "TEST-FM",
            "radio_station_name": "Test Station",
            "time_zone": "UTC",
        }
        assert set(prepared["analysis_json"]) == {
            "translation",
            "title",
            "summary",
            "explanation",
            "disinformation_categories",
            "keywords_detected",
            "language",
            "confidence_scores",
            "political_leaning",
        }

    def test_prepare_snippet_for_review_invalid_date(self, mock_supabase_client, sample_snippet):
        sample_snippet["recorded_at"] = "invalid-date"

        with pytest.raises(ValueError):
            prepare_snippet_for_review(mock_supabase_client, sample_snippet)

    def test_prepare_snippet_for_review_missing_fields(self, mock_supabase_client):
        with pytest.raises(KeyError):
            prepare_snippet_for_review(mock_supabase_client, {"recorded_at": "2024-01-01T00:00:00+00:00"})

    def test_submit_snippet_review_result(self, mock_supabase_client, review_result):
        submit_snippet_review_result(mock_supabase_client, "test-id", review_result, "grounding", "gemini-2.5-pro")

        mock_supabase_client.submit_snippet_review.assert_called_once_with(
            id="test-id",
            translation="Reviewed translation",
            title=review_result["title"],
            summary=review_result["summary"],
            explanation=review_result["explanation"],
            disinformation_categories=review_result["disinformation_categories"],
            keywords_detected=["keyword3"],
            language=review_result["language"],
            confidence_scores={"overall": 40},
            political_leaning={"score": 0.1},
            grounding_metadata="grounding",
            reviewed_by="gemini-2.5-pro",
            thought_summaries="reviewer thoughts",
        )

    def test_submit_snippet_review_result_with_none_values(self, mock_supabase_client):
        response = dict.fromkeys(
            [
                "translation",
                "title",
                "summary",
                "explanation",
                "disinformation_categories",
                "keywords_detected",
                "language",
                "confidence_scores",
                "political_leaning",
            ]
        )

        submit_snippet_review_result(mock_supabase_client, "test-id", response, None, "gemini-2.5-pro")

        kwargs = mock_supabase_client.submit_snippet_review.call_args.kwargs
        assert kwargs["grounding_metadata"] is None
        assert kwargs["thought_summaries"] is None  # not in the response -> .get() default

    def test_fetch_ready_for_review_snippet(self, mock_supabase_client):
        expected_response = {"id": "test-id", "status": "Ready for review"}
        mock_supabase_client.get_a_ready_for_review_snippet_and_reserve_it.return_value = expected_response

        assert fetch_a_ready_for_review_snippet_from_supabase(mock_supabase_client) == expected_response
        mock_supabase_client.get_a_ready_for_review_snippet_and_reserve_it.assert_called_once()

    def test_fetch_ready_for_review_snippet_none(self, mock_supabase_client):
        assert fetch_a_ready_for_review_snippet_from_supabase(mock_supabase_client) is None

    def test_fetch_specific_snippet(self, mock_supabase_client):
        expected_response = {"id": "test-id", "status": "Ready for review"}
        mock_supabase_client.get_snippet_by_id.return_value = expected_response

        assert fetch_a_specific_snippet_from_supabase(mock_supabase_client, "test-id") == expected_response
        mock_supabase_client.get_snippet_by_id.assert_called_once_with(id="test-id")

    # --- process_snippet -------------------------------------------------------

    def _process(self, supabase_client, snippet):
        return asyncio.run(process_snippet(supabase_client, snippet, PROMPT_VERSIONS))

    def test_process_snippet(self, mock_supabase_client, sample_snippet, review_result):
        with patch(
            "processing_pipeline.stage_4.tasks.Stage4Executor.run_async",
            new=AsyncMock(return_value=(review_result, json.dumps({"kb_research": "kb findings"}))),
        ) as mock_run, patch("processing_pipeline.stage_4.tasks.postprocess_snippet") as mock_postprocess:
            self._process(mock_supabase_client, sample_snippet)

        # First review: the stage-3 analysis is backed up before it is overwritten
        mock_supabase_client.update_snippet_previous_analysis.assert_called_once_with("test-id", sample_snippet)
        mock_run.assert_awaited_once_with(
            snippet_id="test-id",
            transcription="Test transcription",
            disinformation_snippet="Test main",
            metadata=mock.ANY,
            analysis_json=mock.ANY,
            recorded_at="2024-01-01T00:00:00+00:00",
            current_time=mock.ANY,
            prompt_versions=PROMPT_VERSIONS,
            reviewer_model=GeminiModel.GEMINI_2_5_PRO,
        )
        assert mock_run.await_args.kwargs["analysis_json"]["translation"] == "Test translation"
        mock_supabase_client.submit_snippet_review.assert_called_once()
        kwargs = mock_supabase_client.submit_snippet_review.call_args.kwargs
        assert kwargs["id"] == "test-id"
        assert kwargs["translation"] == "Reviewed translation"
        # no stage-3 evidence and the gate did not apply, so the reviewer's record passes through unchanged
        assert json.loads(kwargs["grounding_metadata"]) == {"kb_research": "kb findings"}
        assert kwargs["reviewed_by"] == GeminiModel.GEMINI_2_5_PRO.value
        mock_postprocess.assert_called_once_with(
            mock_supabase_client, "test-id", review_result["disinformation_categories"]
        )
        mock_supabase_client.set_snippet_status.assert_not_called()

    def test_process_snippet_reuses_previous_analysis(self, mock_supabase_client, sample_snippet, review_result):
        """A re-review is always based on the original stage-3 analysis, not the last review"""
        sample_snippet["previous_analysis"] = {**sample_snippet, "transcription": "Original transcription"}

        with patch(
            "processing_pipeline.stage_4.tasks.Stage4Executor.run_async",
            new=AsyncMock(return_value=(review_result, None)),
        ) as mock_run, patch("processing_pipeline.stage_4.tasks.postprocess_snippet"):
            self._process(mock_supabase_client, sample_snippet)

        mock_supabase_client.update_snippet_previous_analysis.assert_not_called()
        assert mock_run.await_args.kwargs["transcription"] == "Original transcription"

    def test_process_snippet_with_empty_disinformation_categories(
        self, mock_supabase_client, sample_snippet, review_result
    ):
        review_result["disinformation_categories"] = []

        with patch(
            "processing_pipeline.stage_4.tasks.Stage4Executor.run_async",
            new=AsyncMock(return_value=(review_result, None)),
        ), patch("processing_pipeline.stage_4.tasks.postprocess_snippet") as mock_postprocess:
            self._process(mock_supabase_client, sample_snippet)

        mock_postprocess.assert_called_once_with(mock_supabase_client, "test-id", [])
        mock_supabase_client.submit_snippet_review.assert_called_once()

    def test_process_snippet_error(self, mock_supabase_client, sample_snippet):
        with patch(
            "processing_pipeline.stage_4.tasks.Stage4Executor.run_async",
            new=AsyncMock(side_effect=RuntimeError("Test error")),
        ):
            self._process(mock_supabase_client, sample_snippet)

        mock_supabase_client.submit_snippet_review.assert_not_called()
        mock_supabase_client.set_snippet_status.assert_called_once_with("test-id", "Error", "[Stage 4] Test error")

    def test_process_snippet_retries_transient_errors(self, mock_supabase_client, sample_snippet, review_result):
        overloaded = errors.ServerError(503, {"error": {"message": "overloaded", "status": "UNAVAILABLE"}})
        with patch(
            "processing_pipeline.stage_4.tasks.Stage4Executor.run_async",
            new=AsyncMock(side_effect=[ExceptionGroup("agents failed", [overloaded]), (review_result, None)]),
        ) as mock_run, patch("processing_pipeline.gemini_retry.asyncio.sleep", new=AsyncMock()) as mock_sleep, patch(
            "processing_pipeline.stage_4.tasks.postprocess_snippet"
        ):
            self._process(mock_supabase_client, sample_snippet)

        assert mock_run.await_count == 2
        assert mock_sleep.await_args_list == [call(30)]
        mock_supabase_client.submit_snippet_review.assert_called_once()
        mock_supabase_client.set_snippet_status.assert_not_called()

    def test_process_snippet_exception_group(self, mock_supabase_client, sample_snippet):
        """Errors raised by the ADK agent pipeline arrive as ExceptionGroups; each is listed"""
        group = ExceptionGroup("agents failed", [ValueError("bad value"), KeyError("missing")])
        with patch("processing_pipeline.stage_4.tasks.Stage4Executor.run_async", new=AsyncMock(side_effect=group)):
            self._process(mock_supabase_client, sample_snippet)

        _, status, error_message = mock_supabase_client.set_snippet_status.call_args.args
        assert status == "Error"
        assert error_message == "[Stage 4] - ValueError: bad value\n- KeyError: 'missing'"

    def test_process_snippet_with_missing_fields(self, mock_supabase_client):
        incomplete_snippet = {"id": "test-id", "recorded_at": "2024-01-01T00:00:00+00:00", "previous_analysis": None}

        with patch("processing_pipeline.stage_4.tasks.Stage4Executor.run_async", new=AsyncMock()) as mock_run:
            self._process(mock_supabase_client, incomplete_snippet)

        mock_run.assert_not_awaited()
        mock_supabase_client.set_snippet_status.assert_called_once_with("test-id", "Error", mock.ANY)

    # --- Stage4Executor ------------------------------------------------------------

    def test_stage_4_executor_requires_inputs(self):
        with pytest.raises(ValueError, match=r"All inputs \(transcription, metadata, analysis_json\) must be provided"):
            asyncio.run(
                Stage4Executor.run_async(
                    snippet_id="test-id",
                    transcription=None,
                    disinformation_snippet=None,
                    metadata=None,
                    analysis_json=None,
                    recorded_at="2024-01-01T00:00:00+00:00",
                    current_time="2024-01-02T00:00:00+00:00",
                    prompt_versions=PROMPT_VERSIONS,
                    reviewer_model=GeminiModel.GEMINI_2_5_PRO,
                )
            )

    def test_build_grounding_metadata(self):
        assert Stage4Executor._build_grounding_metadata("", "", "") is None
        assert json.loads(Stage4Executor._build_grounding_metadata("kb findings", "", "kb updated")) == {
            "kb_research": "kb findings",
            "kb_updates": "kb updated",
        }

    # --- analysis_review flow --------------------------------------------------------

    @pytest.fixture
    def mock_process(self):
        with patch("processing_pipeline.stage_4.flows.process_snippet", new=AsyncMock()) as mock_process:
            yield mock_process

    def test_analysis_review_flow(self, mock_supabase_client, sample_snippet, mock_process, monkeypatch):
        mock_supabase_client.get_a_ready_for_review_snippet_and_reserve_it.return_value = sample_snippet
        monkeypatch.setenv("GOOGLE_GEMINI_KEY", "gemini-key")
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

        with patch("processing_pipeline.stage_4.flows.asyncio.sleep", new=AsyncMock()) as mock_sleep:
            asyncio.run(analysis_review(snippet_ids=None, repeat=False))

        # The ADK agents read GOOGLE_API_KEY; the flow copies GOOGLE_GEMINI_KEY into it
        assert os.environ["GOOGLE_API_KEY"] == "gemini-key"
        assert mock_supabase_client.get_active_prompt.call_count == 4
        mock_supabase_client.get_a_ready_for_review_snippet_and_reserve_it.assert_called_once()
        mock_process.assert_awaited_once_with(mock_supabase_client, sample_snippet, PROMPT_VERSIONS)
        mock_sleep.assert_not_awaited()

    def test_analysis_review_with_specific_snippets(self, mock_supabase_client, sample_snippet, mock_process):
        mock_supabase_client.get_snippet_by_id.return_value = sample_snippet

        asyncio.run(analysis_review(snippet_ids=["test-id"], repeat=False))

        mock_supabase_client.get_snippet_by_id.assert_called_once_with(id="test-id")
        mock_supabase_client.set_snippet_status.assert_called_once_with("test-id", "Reviewing")
        mock_supabase_client.get_a_ready_for_review_snippet_and_reserve_it.assert_not_called()
        mock_process.assert_awaited_once_with(mock_supabase_client, sample_snippet, PROMPT_VERSIONS)

    def test_analysis_review_with_specific_ids_not_found(self, mock_supabase_client, mock_process):
        mock_supabase_client.get_snippet_by_id.side_effect = [None, RuntimeError("Database error")]

        with pytest.raises(RuntimeError, match="Database error"):
            asyncio.run(analysis_review(snippet_ids=["test-id-1", "test-id-2"], repeat=False))

        assert mock_supabase_client.get_snippet_by_id.call_args_list == [call(id="test-id-1"), call(id="test-id-2")]
        mock_process.assert_not_awaited()

    def test_analysis_review_with_repeat(self, mock_supabase_client, sample_snippet, mock_process):
        mock_supabase_client.get_a_ready_for_review_snippet_and_reserve_it.side_effect = [sample_snippet, None]
        sleep_calls = []

        async def fake_sleep(seconds):
            sleep_calls.append(seconds)
            if len(sleep_calls) == 2:
                raise StopLoop()

        with patch("processing_pipeline.stage_4.flows.asyncio.sleep", new=fake_sleep), pytest.raises(StopLoop):
            asyncio.run(analysis_review(snippet_ids=None, repeat=True))

        assert sleep_calls == [2, 60]
        mock_process.assert_awaited_once()
