import asyncio
import json
import os
from collections import defaultdict
from unittest import mock
from unittest.mock import AsyncMock, Mock, call, patch

import httpx
import pytest
from google.genai import errors
from google.genai.types import FinishReason, GenerateContentResponseUsageMetadata, ServiceTier, ThinkingLevel

from processing_pipeline.constants import GeminiModel, ProcessingStatus
from processing_pipeline.gemini_retry import GEMINI_HTTP_OPTIONS
from processing_pipeline.stage_3 import (
    Stage3Executor,
    copy_repeat_analysis,
    download_audio_file_from_s3,
    fetch_a_new_snippet_from_supabase,
    fetch_a_specific_snippet_from_supabase,
    find_repeat_source,
    get_metadata,
    in_depth_analysis,
    process_snippet,
    stage_1_excerpt,
    update_snippet_in_supabase,
)
from processing_pipeline.stage_3.executors import USAGE_FIELDS

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


def text_part(text, thought=False):
    """A response part carrying text (or a thought summary) and no tool call"""
    return Mock(text=text, thought=thought, function_call=None)


def model_response(text, parts=(), finish_reason=FinishReason.STOP):
    """A generate_content response double: one candidate, no tool calls, no token usage"""
    return Mock(
        text=text,
        usage_metadata=None,
        candidates=[Mock(content=Mock(parts=list(parts)), finish_reason=finish_reason)],
    )


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
        uploaded.uri = "https://files.example/test-audio"
        uploaded.mime_type = "audio/mpeg"
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
            "radio_station_code": "TEST-FM",
        }

    @pytest.fixture
    def source_snippet(self):
        """An earlier Processed airing of the same content, as get_snippet_by_id(select="*") returns it"""
        return {
            "id": "source-id",
            "transcription": "Source transcription",
            "translation": "Source translation",
            "title": {"english": "Source title"},
            "summary": {"english": "Source summary"},
            "explanation": {"english": "Source explanation"},
            "disinformation_categories": [{"english": "Health", "spanish": "Salud"}],
            "keywords_detected": ["cura"],
            "language": {"primary_language": "es"},
            "confidence_scores": {"overall": 92},
            "emotional_tone": [],
            "context": {"main": "Source context"},
            "political_leaning": {"score": 0},
            "grounding_metadata": "source grounding",
            "thought_summaries": "source thoughts",
            "analyzed_by": "gemini-3.8-flash",
            "stage_3_prompt_version_id": "pv-3",
            "reviewed_at": "2026-11-09T10:00:00+00:00",
            "reviewed_by": "gemini-3.8-flash",
            "status": "Processed",
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

    def test_get_metadata_accepts_fractional_recorded_at(self, sample_snippet):
        # Word-time clips (STAGE2_USE_WORD_TIMES) start on a millisecond, so recorded_at has a fraction.
        sample_snippet["recorded_at"] = "2024-01-01T00:00:12.345+00:00"

        result = get_metadata(sample_snippet)

        assert result["additional_info"]["recorded_at"] == "January 1, 2024 12:00 AM"
        assert result["additional_info"]["recorded_at_iso"] == "2024-01-01T00:00:12.345000+00:00"

    # --- repeat dedup (VER-465) -------------------------------------------------

    def test_stage_1_excerpt(self, sample_snippet):
        assert stage_1_excerpt(sample_snippet) == "Test transcription"
        # Reading the excerpt must not consume the flagged snippet get_metadata needs later
        assert get_metadata(sample_snippet)["transcription"] == "Test transcription"

    def test_stage_1_excerpt_missing(self, sample_snippet):
        sample_snippet["id"] = "other-id"
        assert stage_1_excerpt(sample_snippet) is None

    @pytest.mark.parametrize("stage_1", [None, {"detection_result": None}, {"detection_result": {}}])
    def test_find_repeat_source_without_stage_1_result(self, mock_supabase_client, sample_snippet, stage_1):
        sample_snippet["stage_1_llm_response"] = stage_1

        assert find_repeat_source(mock_supabase_client, sample_snippet, "pv-3") is None
        mock_supabase_client.find_stage3_repeat_source.assert_not_called()

    def test_find_repeat_source(self, mock_supabase_client, sample_snippet, source_snippet):
        mock_supabase_client.find_stage3_repeat_source.return_value = "source-id"
        mock_supabase_client.get_snippet_by_id.return_value = source_snippet

        assert find_repeat_source(mock_supabase_client, sample_snippet, "pv-3") == source_snippet
        mock_supabase_client.find_stage3_repeat_source.assert_called_once_with(
            station="TEST-FM", recorded_at="2024-01-01T00:00:00+00:00", excerpt="Test transcription", prompt_version_id="pv-3"
        )
        mock_supabase_client.get_snippet_by_id.assert_called_once_with(id="source-id", select="*")

    def test_find_repeat_source_no_match(self, mock_supabase_client, sample_snippet):
        mock_supabase_client.find_stage3_repeat_source.return_value = None

        assert find_repeat_source(mock_supabase_client, sample_snippet, "pv-3") is None
        mock_supabase_client.get_snippet_by_id.assert_not_called()

    def test_find_repeat_source_without_excerpt_skips_the_lookup(self, mock_supabase_client, sample_snippet):
        sample_snippet["stage_1_llm_response"]["detection_result"]["flagged_snippets"][0]["transcription"] = ""

        assert find_repeat_source(mock_supabase_client, sample_snippet, "pv-3") is None
        mock_supabase_client.find_stage3_repeat_source.assert_not_called()

    def test_find_repeat_source_without_station_skips_the_lookup(self, mock_supabase_client, sample_snippet):
        sample_snippet["radio_station_code"] = None

        assert find_repeat_source(mock_supabase_client, sample_snippet, "pv-3") is None
        mock_supabase_client.find_stage3_repeat_source.assert_not_called()

    @pytest.mark.parametrize("failing", ["find_stage3_repeat_source", "get_snippet_by_id"])
    def test_find_repeat_source_lookup_error_means_no_source(self, mock_supabase_client, sample_snippet, failing):
        mock_supabase_client.find_stage3_repeat_source.return_value = "source-id"
        getattr(mock_supabase_client, failing).side_effect = RuntimeError("db down")

        assert find_repeat_source(mock_supabase_client, sample_snippet, "pv-3") is None

    def test_find_repeat_source_vanished_source(self, mock_supabase_client, sample_snippet):
        mock_supabase_client.find_stage3_repeat_source.return_value = "source-id"
        mock_supabase_client.get_snippet_by_id.return_value = None

        assert find_repeat_source(mock_supabase_client, sample_snippet, "pv-3") is None

    def test_copy_repeat_analysis(self, mock_supabase_client, sample_snippet, source_snippet):
        order = []
        mock_supabase_client.update_snippet.side_effect = lambda **_: order.append("update")
        with patch(
            "processing_pipeline.stage_3.tasks.postprocess_snippet", side_effect=lambda *_: order.append("postprocess")
        ) as mock_postprocess:
            assert copy_repeat_analysis(mock_supabase_client, sample_snippet, source_snippet) is True

        mock_supabase_client.update_snippet.assert_called_once_with(
            id="test-id",
            transcription="Source transcription",
            translation="Source translation",
            title={"english": "Source title"},
            summary={"english": "Source summary"},
            explanation={"english": "Source explanation"},
            disinformation_categories=[{"english": "Health", "spanish": "Salud"}],
            keywords_detected=["cura"],
            language={"primary_language": "es"},
            confidence_scores={"overall": 92},
            emotional_tone=[],
            context={"main": "Source context"},
            political_leaning={"score": 0},
            grounding_metadata="source grounding",
            thought_summaries=None,
            analyzed_by="gemini-3.8-flash",
            status=ProcessingStatus.PROCESSED,
            error_message=None,
            stage_3_prompt_version_id="pv-3",
            reviewed_at="2026-11-09T10:00:00+00:00",
            reviewed_by="gemini-3.8-flash",
            repeat_of="source-id",
        )
        mock_postprocess.assert_called_once_with(
            mock_supabase_client, "test-id", [{"english": "Health", "spanish": "Salud"}]
        )
        assert order == ["update", "postprocess"]

    def test_copy_repeat_analysis_copies_every_field_stage_3_writes(self, mock_supabase_client, mock_gemini_response):
        update_snippet_in_supabase(
            supabase_client=mock_supabase_client, snippet_id="x", gemini_response=mock_gemini_response,
            grounding_metadata=None, thought_summaries=None, analyzed_by=None, status=None, error_message=None,
        )
        stage_3_fields = set(mock_supabase_client.update_snippet.call_args.kwargs)
        mock_supabase_client.reset_mock()

        with patch("processing_pipeline.stage_3.tasks.postprocess_snippet"):
            copy_repeat_analysis(mock_supabase_client, {"id": "x"}, defaultdict(lambda: None, id="s"))

        assert stage_3_fields <= set(mock_supabase_client.update_snippet.call_args.kwargs)

    def test_copy_repeat_analysis_write_failure_falls_back(self, mock_supabase_client, sample_snippet, source_snippet):
        mock_supabase_client.update_snippet.side_effect = RuntimeError("write failed")
        with patch("processing_pipeline.stage_3.tasks.postprocess_snippet") as mock_postprocess:
            assert copy_repeat_analysis(mock_supabase_client, sample_snippet, source_snippet) is False

        mock_postprocess.assert_not_called()
        mock_supabase_client.set_snippet_status.assert_not_called()

    def test_copy_repeat_analysis_postprocess_failure_is_an_error(
        self, mock_supabase_client, sample_snippet, source_snippet
    ):
        with patch("processing_pipeline.stage_3.tasks.postprocess_snippet", side_effect=RuntimeError("labels down")):
            assert copy_repeat_analysis(mock_supabase_client, sample_snippet, source_snippet) is True

        mock_supabase_client.set_snippet_status.assert_called_once_with(
            "test-id", ProcessingStatus.ERROR, "[Stage 3 repeat] RuntimeError: labels down"
        )

    def test_copy_repeat_analysis_never_raises(self, mock_supabase_client, sample_snippet, source_snippet):
        mock_supabase_client.set_snippet_status.side_effect = RuntimeError("db down")
        with patch("processing_pipeline.stage_3.tasks.postprocess_snippet", side_effect=RuntimeError("labels down")):
            assert copy_repeat_analysis(mock_supabase_client, sample_snippet, source_snippet) is True

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
            service_tier=None,
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

    @pytest.mark.parametrize(
        "model, overall, expected",
        [
            ("gemini-3.8-flash", 90, ProcessingStatus.READY_FOR_REVIEW),
            ("gemini-3.8-flash", 89, ProcessingStatus.PROCESSED),
            ("gemini-3.1-flash-lite", 90, ProcessingStatus.READY_FOR_REVIEW),
            ("gemini-2.5-pro", 94, ProcessingStatus.PROCESSED),
            ("gemini-2.5-pro", 95, ProcessingStatus.READY_FOR_REVIEW),
        ],
    )
    def test_process_snippet_review_line_depends_on_model(
        self, mock_supabase_client, sample_snippet, analysis_result, monkeypatch, model, overall, expected
    ):
        monkeypatch.setenv("STAGE3_MAIN_MODEL", model)
        analysis_result["response"]["confidence_scores"]["overall"] = overall
        with patch(
            "processing_pipeline.stage_3.tasks.Stage3Executor.run_async", new=AsyncMock(return_value=analysis_result)
        ), patch("processing_pipeline.stage_3.tasks.postprocess_snippet"):
            self._process(mock_supabase_client, sample_snippet, skip_review=False)

        assert mock_supabase_client.update_snippet.call_args.kwargs["status"] == expected

    @pytest.mark.parametrize(
        "main_model, fallback_model, expected",
        [
            ("gemini-3.8-flash", "gemini-2.5-pro", ProcessingStatus.PROCESSED),
            ("gemini-2.5-pro", "gemini-3.5-flash", ProcessingStatus.READY_FOR_REVIEW),
        ],
    )
    def test_process_snippet_review_line_follows_the_fallback_model(
        self, mock_supabase_client, sample_snippet, analysis_result, monkeypatch, main_model, fallback_model, expected
    ):
        monkeypatch.setenv("STAGE3_MAIN_MODEL", main_model)
        monkeypatch.setenv("STAGE3_FALLBACK_MODEL", fallback_model)
        analysis_result["response"]["confidence_scores"]["overall"] = 92
        server_error = errors.ServerError(503, {"error": {"message": "overloaded", "status": "UNAVAILABLE"}})
        with patch(
            "processing_pipeline.stage_3.tasks.Stage3Executor.run_async",
            new=AsyncMock(side_effect=[server_error, analysis_result]),
        ), patch("processing_pipeline.stage_3.tasks.postprocess_snippet"):
            self._process(mock_supabase_client, sample_snippet, skip_review=False)

        kwargs = mock_supabase_client.update_snippet.call_args.kwargs
        assert kwargs["analyzed_by"] == fallback_model
        assert kwargs["status"] == expected

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

    def test_process_snippet_models_come_from_env(
        self, mock_supabase_client, sample_snippet, analysis_result, monkeypatch
    ):
        monkeypatch.setenv("STAGE3_MAIN_MODEL", "gemini-3.8-flash")
        monkeypatch.setenv("STAGE3_FALLBACK_MODEL", "gemini-3.5-flash")
        server_error = errors.ClientError(400, {"error": {"message": "invalid", "status": "INVALID_ARGUMENT"}})
        with patch(
            "processing_pipeline.stage_3.tasks.Stage3Executor.run_async",
            new=AsyncMock(side_effect=[server_error, analysis_result]),
        ) as mock_run, patch("processing_pipeline.stage_3.tasks.postprocess_snippet"):
            self._process(mock_supabase_client, sample_snippet, skip_review=True)

        assert mock_run.await_args_list[0].kwargs["model_name"] is GeminiModel.GEMINI_3_8_FLASH
        assert mock_run.await_args_list[1].kwargs["model_name"] is GeminiModel.GEMINI_3_5_FLASH
        # analyzed_by records the model that actually produced the analysis
        assert mock_supabase_client.update_snippet.call_args.kwargs["analyzed_by"] == "gemini-3.5-flash"

    def test_process_snippet_flex_applies_to_the_main_model_only(
        self, mock_supabase_client, sample_snippet, analysis_result, monkeypatch
    ):
        monkeypatch.setenv("STAGE3_SERVICE_TIER", "flex")
        bad_request = errors.ClientError(400, {"error": {"message": "invalid", "status": "INVALID_ARGUMENT"}})
        with patch(
            "processing_pipeline.stage_3.tasks.Stage3Executor.run_async",
            new=AsyncMock(side_effect=[bad_request, analysis_result]),
        ) as mock_run, patch("processing_pipeline.stage_3.tasks.postprocess_snippet"):
            self._process(mock_supabase_client, sample_snippet, skip_review=True)

        assert mock_run.await_args_list[0].kwargs["service_tier"] is ServiceTier.FLEX
        assert mock_run.await_args_list[1].kwargs["service_tier"] is None

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

    def test_process_snippet_retries_transient_errors_then_succeeds(
        self, mock_supabase_client, sample_snippet, analysis_result
    ):
        overloaded = errors.ServerError(503, {"error": {"message": "overloaded", "status": "UNAVAILABLE"}})
        with patch(
            "processing_pipeline.stage_3.tasks.Stage3Executor.run_async",
            new=AsyncMock(side_effect=[overloaded, overloaded, ValueError("No response from Gemini."), analysis_result]),
        ) as mock_run, patch("processing_pipeline.gemini_retry.asyncio.sleep", new=AsyncMock()) as mock_sleep, patch(
            "processing_pipeline.stage_3.tasks.postprocess_snippet"
        ):
            self._process(mock_supabase_client, sample_snippet, skip_review=True)

        # attempt 1: pro 503 -> flash 503; attempt 2: pro empty; attempt 3: pro ok
        assert [c.kwargs["model_name"] for c in mock_run.await_args_list] == [
            GeminiModel.GEMINI_2_5_PRO,
            GeminiModel.GEMINI_2_5_FLASH,
            GeminiModel.GEMINI_2_5_PRO,
            GeminiModel.GEMINI_2_5_PRO,
        ]
        assert mock_sleep.await_args_list == [call(30), call(120)]
        mock_supabase_client.set_snippet_status.assert_not_called()
        assert mock_supabase_client.update_snippet.call_args.kwargs["status"] == ProcessingStatus.PROCESSED

    def test_process_snippet_gives_up_after_the_last_retry(self, mock_supabase_client, sample_snippet):
        quota = errors.ClientError(429, {"error": {"message": "quota", "status": "RESOURCE_EXHAUSTED"}})
        with patch(
            "processing_pipeline.stage_3.tasks.Stage3Executor.run_async", new=AsyncMock(side_effect=quota)
        ) as mock_run, patch("processing_pipeline.gemini_retry.asyncio.sleep", new=AsyncMock()) as mock_sleep:
            self._process(mock_supabase_client, sample_snippet, skip_review=True)

        assert mock_run.await_count == 8  # 4 attempts x (pro, flash)
        assert mock_sleep.await_args_list == [call(30), call(120), call(300)]
        mock_supabase_client.update_snippet.assert_not_called()
        snippet_id, status, error_message = mock_supabase_client.set_snippet_status.call_args.args
        assert (snippet_id, status) == ("test-id", ProcessingStatus.ERROR)
        assert error_message.startswith("ClientError: 429")

    def test_process_snippet_does_not_retry_other_client_errors(self, mock_supabase_client, sample_snippet):
        bad_request = errors.ClientError(400, {"error": {"message": "bad audio", "status": "INVALID_ARGUMENT"}})
        with patch(
            "processing_pipeline.stage_3.tasks.Stage3Executor.run_async", new=AsyncMock(side_effect=bad_request)
        ) as mock_run, patch("processing_pipeline.gemini_retry.asyncio.sleep", new=AsyncMock()) as mock_sleep:
            self._process(mock_supabase_client, sample_snippet, skip_review=True)

        assert mock_run.await_count == 2  # pro, then the flash fallback; no retry round
        mock_sleep.assert_not_awaited()
        assert mock_supabase_client.set_snippet_status.call_args.args[1] == ProcessingStatus.ERROR

    def test_process_snippet_bad_service_tier_fails_without_retries(
        self, mock_supabase_client, sample_snippet, monkeypatch
    ):
        monkeypatch.setenv("STAGE3_SERVICE_TIER", "flexx")
        with patch("processing_pipeline.stage_3.tasks.Stage3Executor.run_async", new=AsyncMock()) as mock_run, patch(
            "processing_pipeline.gemini_retry.asyncio.sleep", new=AsyncMock()
        ) as mock_sleep:
            self._process(mock_supabase_client, sample_snippet, skip_review=True)

        mock_run.assert_not_awaited()
        mock_sleep.assert_not_awaited()
        snippet_id, status, error_message = mock_supabase_client.set_snippet_status.call_args.args
        assert (snippet_id, status) == ("test-id", ProcessingStatus.ERROR)
        assert "STAGE3_SERVICE_TIER='flexx'" in error_message

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
        analysis_response = model_response("not json at all")
        restructure_response = Mock(parsed=None, candidates=[Mock(finish_reason=FinishReason.STOP)])
        mock_gemini_client.aio.models.generate_content.side_effect = [analysis_response, restructure_response] * 4

        with patch("processing_pipeline.gemini_retry.asyncio.sleep", new=AsyncMock()) as mock_sleep:
            self._process(mock_supabase_client, sample_snippet, skip_review=False, gemini_client=mock_gemini_client)

        assert mock_sleep.await_count == 3
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
        analysis_response = model_response('{"test": "response"}')
        restructure_response = Mock(parsed={"test": "response", "is_convertible": True})
        mock_gemini_client.aio.models.generate_content.side_effect = [analysis_response, restructure_response]

        result = self._run_executor(mock_gemini_client)

        assert result["response"] == {"test": "response", "is_convertible": True}
        # no verification_evidence in the output, no tool ran
        assert json.loads(result["grounding_metadata"]) == {
            "tool_usage": {"calls": {}, "sources_by_tool": {}},
            "token_usage": dict.fromkeys(USAGE_FIELDS, 0),
        }
        assert result["thought_summaries"] is None
        assert result["usage"] == dict.fromkeys(USAGE_FIELDS, 0)  # the response double reports no usage
        assert mock_gemini_client.aio.models.generate_content.await_count == 2
        first_call = mock_gemini_client.aio.models.generate_content.await_args_list[0].kwargs
        assert first_call["model"] == GeminiModel.GEMINI_2_5_PRO
        prompt_part, audio_part = first_call["contents"][0].parts
        assert prompt_part.text.startswith("Analyze this clip.")
        assert "BREAKING NEWS PROTOCOL" not in prompt_part.text  # recording is years old
        assert audio_part.file_data.file_uri == "https://files.example/test-audio"
        assert first_call["config"].automatic_function_calling.disable is True
        second_call = mock_gemini_client.aio.models.generate_content.await_args_list[1].kwargs
        assert second_call["model"] == GeminiModel.GEMINI_2_5_FLASH
        assert second_call["config"].response_schema is not None
        mock_gemini_client.files.upload.assert_called_once_with(file="test.mp3")
        mock_gemini_client.files.delete.assert_called_once_with(name="files/test-audio")

    def test_stage_3_executor_thinking_and_restructure_model_on_gemini_3(self, mock_gemini_client, monkeypatch):
        monkeypatch.setenv("STAGE3_RESTRUCTURE_MODEL", "gemini-3.5-flash-lite")
        analysis_response = model_response('{"test": "response"}')
        restructure_response = Mock(parsed={"test": "response", "is_convertible": True})
        mock_gemini_client.aio.models.generate_content.side_effect = [analysis_response, restructure_response]

        asyncio.run(
            Stage3Executor.run_async(
                gemini_client=mock_gemini_client,
                model_name=GeminiModel.GEMINI_3_8_FLASH,
                audio_file="test.mp3",
                metadata={"additional_info": {"recorded_at": "January 1, 2024 12:00 AM"}},
                prompt_version=PROMPT_VERSION,
            )
        )

        first_call, second_call = (c.kwargs for c in mock_gemini_client.aio.models.generate_content.await_args_list)
        assert first_call["model"] is GeminiModel.GEMINI_3_8_FLASH
        assert first_call["config"].thinking_config.thinking_level == ThinkingLevel.MEDIUM
        assert first_call["config"].thinking_config.thinking_budget is None
        assert first_call["config"].thinking_config.include_thoughts is True
        assert second_call["model"] is GeminiModel.GEMINI_3_5_FLASH_LITE
        assert second_call["config"].thinking_config.thinking_level == ThinkingLevel.MINIMAL

    def test_stage_3_executor_default_thinking_on_2_5(self, mock_gemini_client):
        analysis_response = model_response('{"test": "response"}')
        restructure_response = Mock(parsed={"test": "response", "is_convertible": True})
        mock_gemini_client.aio.models.generate_content.side_effect = [analysis_response, restructure_response]

        self._run_executor(mock_gemini_client)

        first_call, second_call = (c.kwargs for c in mock_gemini_client.aio.models.generate_content.await_args_list)
        assert first_call["config"].thinking_config.thinking_budget == 4096
        assert first_call["config"].thinking_config.include_thoughts is True
        assert second_call["config"].thinking_config.thinking_budget == 0

    def test_stage_3_executor_collects_thoughts(self, mock_gemini_client):
        thought_part = text_part("thinking...", thought=True)
        answer_part = text_part('{"test": "response"}')
        analysis_response = model_response('{"test": "response"}', parts=[thought_part, answer_part])
        restructure_response = Mock(parsed={"test": "response", "is_convertible": True})
        mock_gemini_client.aio.models.generate_content.side_effect = [analysis_response, restructure_response]

        result = self._run_executor(mock_gemini_client)

        assert result["thought_summaries"] == "thinking..."

    def test_stage_3_executor_stores_token_usage_in_grounding_metadata(self, mock_gemini_client):
        analysis_response = model_response('{"test": "response"}')
        analysis_response.usage_metadata = GenerateContentResponseUsageMetadata(
            prompt_token_count=40_000, cached_content_token_count=32_000, candidates_token_count=900
        )
        restructure_response = Mock(parsed={"test": "response", "is_convertible": True})
        mock_gemini_client.aio.models.generate_content.side_effect = [analysis_response, restructure_response]

        result = self._run_executor(mock_gemini_client)

        token_usage = json.loads(result["grounding_metadata"])["token_usage"]
        assert token_usage == result["usage"]
        assert token_usage["cached_content_token_count"] == 32_000
        assert token_usage["prompt_token_count"] == 40_000

    def test_stage_3_executor_keeps_result_when_delete_fails(self, mock_gemini_client):
        mock_gemini_client.aio.models.generate_content.side_effect = [
            model_response('{"x": 1}'),
            Mock(parsed={"is_convertible": True}),
        ]
        mock_gemini_client.files.delete.side_effect = httpx.ReadTimeout("stalled")

        result = self._run_executor(mock_gemini_client)

        assert result["response"] == {"is_convertible": True}

    def test_stage_3_executor_waits_for_upload_processing(self, mock_gemini_client):
        processing = Mock(name="files/test-audio")
        processing.state.name = "PROCESSING"
        processing.name = "files/test-audio"
        mock_gemini_client.files.upload.return_value = processing
        mock_gemini_client.aio.models.generate_content.side_effect = [
            model_response('{"x": 1}'),
            Mock(parsed={"is_convertible": True}),
        ]

        with patch("processing_pipeline.stage_3.executors.asyncio.sleep", new=AsyncMock()) as mock_sleep:
            self._run_executor(mock_gemini_client)

        mock_sleep.assert_awaited_once_with(1)
        mock_gemini_client.files.get.assert_called_once_with(name="files/test-audio")

    def test_stage_3_executor_max_tokens(self, mock_gemini_client):
        mock_gemini_client.aio.models.generate_content.return_value = model_response(
            None, finish_reason=FinishReason.MAX_TOKENS
        )

        with pytest.raises(ValueError, match="too long"):
            self._run_executor(mock_gemini_client)

        mock_gemini_client.files.delete.assert_called_once()

    def test_stage_3_executor_not_convertible(self, mock_gemini_client):
        mock_gemini_client.aio.models.generate_content.side_effect = [
            model_response("prose"),
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

        mock_flow_deps["genai"].Client.assert_called_once_with(api_key="test-key", http_options=GEMINI_HTTP_OPTIONS)
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

    @pytest.fixture
    def mock_dedup(self):
        with patch("processing_pipeline.stage_3.flows.find_repeat_source") as mock_find, patch(
            "processing_pipeline.stage_3.flows.copy_repeat_analysis"
        ) as mock_copy:
            yield {"find": mock_find, "copy": mock_copy}

    def test_in_depth_analysis_copies_a_repeat(
        self, mock_supabase_client, mock_s3_client, sample_snippet, source_snippet, mock_flow_deps, mock_dedup, monkeypatch
    ):
        monkeypatch.setenv("STAGE3_REPEAT_DEDUP", "true")
        mock_supabase_client.get_a_new_snippet_and_reserve_it.return_value = sample_snippet
        mock_dedup["find"].return_value = source_snippet
        mock_dedup["copy"].return_value = True

        asyncio.run(in_depth_analysis(snippet_ids=None, skip_review=False, repeat=False))

        mock_dedup["find"].assert_called_once_with(mock_supabase_client, sample_snippet, "pv-3")
        mock_dedup["copy"].assert_called_once_with(mock_supabase_client, sample_snippet, source_snippet)
        mock_s3_client.download_file.assert_not_called()
        mock_flow_deps["process"].assert_not_awaited()

    def test_in_depth_analysis_runs_stage_3_without_a_repeat(
        self, mock_supabase_client, mock_s3_client, sample_snippet, mock_flow_deps, mock_dedup, monkeypatch
    ):
        monkeypatch.setenv("STAGE3_REPEAT_DEDUP", "true")
        mock_supabase_client.get_a_new_snippet_and_reserve_it.return_value = sample_snippet
        mock_dedup["find"].return_value = None

        asyncio.run(in_depth_analysis(snippet_ids=None, skip_review=False, repeat=False))

        mock_dedup["copy"].assert_not_called()
        mock_flow_deps["process"].assert_awaited_once()

    def test_in_depth_analysis_runs_stage_3_when_the_copy_write_fails(
        self, mock_supabase_client, mock_s3_client, sample_snippet, source_snippet, mock_flow_deps, mock_dedup, monkeypatch
    ):
        monkeypatch.setenv("STAGE3_REPEAT_DEDUP", "true")
        mock_supabase_client.get_a_new_snippet_and_reserve_it.return_value = sample_snippet
        mock_dedup["find"].return_value = source_snippet
        mock_dedup["copy"].return_value = False

        asyncio.run(in_depth_analysis(snippet_ids=None, skip_review=False, repeat=False))

        mock_flow_deps["process"].assert_awaited_once()

    def test_in_depth_analysis_keeps_looping_after_a_copy(
        self, mock_supabase_client, mock_s3_client, sample_snippet, source_snippet, mock_flow_deps, mock_dedup, monkeypatch
    ):
        monkeypatch.setenv("STAGE3_REPEAT_DEDUP", "true")
        mock_supabase_client.get_a_new_snippet_and_reserve_it.side_effect = [sample_snippet, None]
        mock_dedup["find"].return_value = source_snippet
        mock_dedup["copy"].return_value = True
        sleep_calls = []

        async def fake_sleep(seconds):
            sleep_calls.append(seconds)
            if len(sleep_calls) == 2:
                raise StopLoop()

        with patch("processing_pipeline.stage_3.flows.asyncio.sleep", new=fake_sleep), pytest.raises(StopLoop):
            asyncio.run(in_depth_analysis(snippet_ids=None, skip_review=True, repeat=True))

        assert sleep_calls == [2, 60]
        mock_dedup["find"].assert_called_once()

    def test_in_depth_analysis_dedup_off_by_default(
        self, mock_supabase_client, mock_s3_client, sample_snippet, mock_flow_deps, mock_dedup, monkeypatch
    ):
        monkeypatch.delenv("STAGE3_REPEAT_DEDUP", raising=False)
        mock_supabase_client.get_a_new_snippet_and_reserve_it.return_value = sample_snippet

        asyncio.run(in_depth_analysis(snippet_ids=None, skip_review=False, repeat=False))

        mock_dedup["find"].assert_not_called()
        mock_flow_deps["process"].assert_awaited_once()

    def test_in_depth_analysis_by_id_never_dedups(
        self, mock_supabase_client, mock_s3_client, sample_snippet, mock_flow_deps, mock_dedup, monkeypatch
    ):
        monkeypatch.setenv("STAGE3_REPEAT_DEDUP", "true")
        mock_supabase_client.get_snippet_by_id.return_value = sample_snippet

        asyncio.run(in_depth_analysis(snippet_ids=["test-id"], skip_review=False, repeat=False))

        mock_dedup["find"].assert_not_called()
        mock_flow_deps["process"].assert_awaited_once()
