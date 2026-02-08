from unittest import mock
from unittest.mock import Mock, patch
import pytest
from processing_pipeline.stage_3 import (
    fetch_a_specific_snippet_from_supabase,
    fetch_a_new_snippet_from_supabase,
    download_audio_file_from_s3,
    update_snippet_in_supabase,
    get_metadata,
    process_snippet,
    in_depth_analysis,
    Stage3Executor,
)
from processing_pipeline.constants import GeminiModel


class TestStage3:
    @pytest.fixture
    def mock_supabase_client(self):
        """Create a mock Supabase client"""
        with patch("processing_pipeline.stage_3.flows.SupabaseClient") as MockSupabaseClient:
            mock_client = Mock()
            mock_client.get_snippet_by_id.return_value = None
            mock_client.get_a_new_snippet_and_reserve_it.return_value = None
            mock_client.set_snippet_status.return_value = None
            mock_client.update_snippet.return_value = None
            MockSupabaseClient.return_value = mock_client
            yield mock_client

    @pytest.fixture
    def mock_s3_client(self):
        """Create a mock S3 client"""
        with patch("boto3.client") as mock:
            s3_client = Mock()
            mock.return_value = s3_client
            yield s3_client

    @pytest.fixture
    def mock_gemini_response(self):
        """Create a mock Gemini response"""
        return {
            "transcription": "Test transcription",
            "translation": "Test translation",
            "title": "Test title",
            "summary": "Test summary",
            "explanation": "Test explanation",
            "disinformation_categories": [
                {
                    "english": "Misinformation",
                    "spanish": "Desinformación",
                },
            ],
            "keywords_detected": ["keyword1", "keyword2"],
            "language": "es",
            "confidence_scores": {"accuracy": 0.9},
            "emotional_tone": "neutral",
            "context": "Test context",
            "political_leaning": "neutral",
        }

    @pytest.fixture
    def sample_snippet(self):
        """Create a sample snippet for testing"""
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
                            "start_time": "00:00:30",  # Added this
                            "end_time": "00:01:30",  # Added this
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

    def test_fetch_specific_snippet(self, mock_supabase_client):
        """Test fetching a specific snippet"""
        expected_response = {"id": "test-id", "status": "New"}
        mock_supabase_client.get_snippet_by_id.return_value = expected_response

        result = fetch_a_specific_snippet_from_supabase(mock_supabase_client, "test-id")

        assert result == expected_response
        mock_supabase_client.get_snippet_by_id.assert_called_once_with(
            id="test-id",
            select='*, audio_file(radio_station_name, radio_station_code, location_state, location_city, recorded_at, recording_day_of_week), stage_1_llm_response("detection_result")',
        )

    def test_fetch_new_snippet(self, mock_supabase_client):
        """Test fetching a new snippet"""
        expected_response = {"id": "test-id", "status": "New"}
        mock_supabase_client.get_a_new_snippet_and_reserve_it.return_value = expected_response

        result = fetch_a_new_snippet_from_supabase(mock_supabase_client)

        assert result == expected_response
        mock_supabase_client.get_a_new_snippet_and_reserve_it.assert_called_once()

    def test_download_audio_file(self, mock_s3_client):
        """Test downloading audio file from S3"""
        result = download_audio_file_from_s3(mock_s3_client, "test-bucket", "test/path.mp3")

        assert result == "path.mp3"
        mock_s3_client.download_file.assert_called_once_with(
            "test-bucket",
            "test/path.mp3",
            "path.mp3",
        )

    def test_update_snippet(self, mock_supabase_client, mock_gemini_response):
        """Test updating snippet"""
        update_snippet_in_supabase(
            supabase_client=mock_supabase_client,
            snippet_id="test-id",
            gemini_response=mock_gemini_response,
            grounding_metadata=None,
            status="Processed",
            error_message=None,
        )

        mock_supabase_client.update_snippet.assert_called_once()

    def test_get_metadata(self, sample_snippet):
        """Test metadata extraction"""
        result = get_metadata(sample_snippet)

        assert "transcription" in result
        assert "additional_info" in result
        assert result["additional_info"]["time_zone"] == "UTC"
        assert result["start_time"] == "00:30"
        assert result["end_time"] == "01:30"
        assert result["duration"] == "01:00"

    @patch("processing_pipeline.stage_3.Stage3Executor.run")
    def test_process_snippet_skip_review_false(
        self, mock_run, mock_supabase_client, sample_snippet, mock_gemini_response
    ):
        """Test processing a snippet with skip_review=False"""
        mock_run.return_value = (mock_gemini_response, "test_grounding_metadata")

        process_snippet(mock_supabase_client, sample_snippet, "test.mp3", "test-key", skip_review=False)

        # Verify update_snippet was called with "Ready for review" status
        mock_supabase_client.update_snippet.assert_called_once_with(
            id=sample_snippet["id"],
            transcription=mock_gemini_response["transcription"],
            translation=mock_gemini_response["translation"],
            title=mock_gemini_response["title"],
            summary=mock_gemini_response["summary"],
            explanation=mock_gemini_response["explanation"],
            disinformation_categories=mock_gemini_response["disinformation_categories"],
            keywords_detected=mock_gemini_response["keywords_detected"],
            language=mock_gemini_response["language"],
            confidence_scores=mock_gemini_response["confidence_scores"],
            emotional_tone=mock_gemini_response["emotional_tone"],
            context=mock_gemini_response["context"],
            political_leaning=mock_gemini_response["political_leaning"],
            grounding_metadata="test_grounding_metadata",
            status="Ready for review",
            error_message=None,
        )

    @patch("processing_pipeline.stage_3.tasks.postprocess_snippet")
    @patch("processing_pipeline.stage_3.Stage3Executor.run")
    def test_process_snippet_skip_review_true(
        self, mock_run, mock_postprocess, mock_supabase_client, sample_snippet, mock_gemini_response
    ):
        """Test processing a snippet with skip_review=True"""
        mock_run.return_value = (mock_gemini_response, "test_grounding_metadata")

        process_snippet(mock_supabase_client, sample_snippet, "test.mp3", "test-key", skip_review=True)

        # Verify update_snippet was called with "Processed" status
        mock_supabase_client.update_snippet.assert_called_once_with(
            id=sample_snippet["id"],
            transcription=mock_gemini_response["transcription"],
            translation=mock_gemini_response["translation"],
            title=mock_gemini_response["title"],
            summary=mock_gemini_response["summary"],
            explanation=mock_gemini_response["explanation"],
            disinformation_categories=mock_gemini_response["disinformation_categories"],
            keywords_detected=mock_gemini_response["keywords_detected"],
            language=mock_gemini_response["language"],
            confidence_scores=mock_gemini_response["confidence_scores"],
            emotional_tone=mock_gemini_response["emotional_tone"],
            context=mock_gemini_response["context"],
            political_leaning=mock_gemini_response["political_leaning"],
            grounding_metadata="test_grounding_metadata",
            status="Processed",
            error_message=None,
        )

        # Verify postprocess_snippet was called
        mock_postprocess.assert_called_once_with(
            mock_supabase_client, sample_snippet["id"], mock_gemini_response["disinformation_categories"]
        )

    @patch("google.genai.Client")
    def test_process_snippet_error(self, mock_client_class, mock_supabase_client, sample_snippet):
        """Test processing snippet with error"""
        # Configure mock audio file
        mock_audio_file = Mock()
        mock_audio_file.state.name = "PROCESSED"
        mock_audio_file.name = "test-audio-file"

        # Configure mock client to raise error
        mock_client = Mock()
        mock_client.files.upload.return_value = mock_audio_file
        mock_client.files.get.return_value = mock_audio_file
        mock_client.files.delete = Mock()
        mock_client.models.generate_content.side_effect = Exception("Test error")

        mock_client_class.return_value = mock_client

        process_snippet(mock_supabase_client, sample_snippet, "test.mp3", "test-key", skip_review=False)

        mock_supabase_client.set_snippet_status.assert_called_with(sample_snippet["id"], "Error", "Test error")

    @patch("google.genai.Client")
    def test_stage_3_executor(self, mock_client_class):
        """Test Stage3Executor"""
        mock_audio_file = Mock()
        mock_audio_file.state.name = "PROCESSED"
        mock_audio_file.name = "test-audio-file"

        # Configure mock client
        mock_client = Mock()
        mock_client.files.upload.return_value = mock_audio_file
        mock_client.files.get.return_value = mock_audio_file
        mock_client.files.delete = Mock()

        # Mock the analysis response with grounding metadata
        mock_analysis_response = Mock()
        mock_analysis_response.text = '{"test": "response"}'
        mock_analysis_response.candidates = [Mock(grounding_metadata="test_grounding_metadata")]

        # Mock the structured response
        mock_structured_response = Mock()
        mock_structured_response.parsed = {"test": "response", "is_convertible": True}

        # Return different responses for different calls
        mock_client.models.generate_content.side_effect = [mock_analysis_response, mock_structured_response]

        mock_client_class.return_value = mock_client

        result = Stage3Executor.run(
            gemini_key="test-key",
            model_name=GeminiModel.GEMINI_FLASH_LATEST,
            audio_file="test.mp3",
            metadata={"test": "metadata"},
        )

        # Result should be a tuple (response, grounding_metadata)
        assert isinstance(result, tuple)
        assert len(result) == 2
        response, grounding_metadata = result
        assert isinstance(response, dict)
        assert grounding_metadata is not None

    def test_stage_3_executor_without_api_key(self):
        """Test Stage3Executor without API key"""
        with pytest.raises(ValueError, match="Google Gemini API key was not set!"):
            Stage3Executor.run(None, GeminiModel.GEMINI_FLASH_LATEST, "test.mp3", {})

    @patch("time.sleep")
    def test_in_depth_analysis_flow(self, mock_sleep, mock_supabase_client, mock_s3_client, sample_snippet):
        """Test in-depth analysis flow"""
        mock_supabase_client.get_a_new_snippet_and_reserve_it.return_value = sample_snippet

        with patch("os.remove"):
            in_depth_analysis(snippet_ids=None, repeat=False, skip_review=True)

            mock_supabase_client.get_a_new_snippet_and_reserve_it.assert_called_once()
            mock_s3_client.download_file.assert_called_once()

    def test_in_depth_analysis_with_specific_snippets(self, mock_supabase_client, mock_s3_client, sample_snippet):
        """Test in-depth analysis with specific snippet IDs"""
        mock_supabase_client.get_snippet_by_id.return_value = sample_snippet

        with patch("os.remove"):
            in_depth_analysis(snippet_ids=["test-id"], repeat=False, skip_review=True)

            mock_supabase_client.get_snippet_by_id.assert_called_once_with(
                id="test-id",
                select='*, audio_file(radio_station_name, radio_station_code, location_state, location_city, recorded_at, recording_day_of_week), stage_1_llm_response("detection_result")',
            )
            mock_s3_client.download_file.assert_called_once()

    def test_in_depth_analysis_with_repeat(self, mock_supabase_client, mock_s3_client, sample_snippet):
        """Test in-depth analysis with repeat enabled"""
        # Mock responses for consecutive calls
        mock_supabase_client.get_a_new_snippet_and_reserve_it.side_effect = [
            sample_snippet,
            None,  # Second call returns None to end the loop
            None,  # Add an extra None to prevent StopIteration
        ]

        with patch("os.remove"), patch("time.sleep") as mock_sleep, patch(
            "processing_pipeline.stage_3.flows.process_snippet"
        ) as mock_process:

            try:
                in_depth_analysis(snippet_ids=None, repeat=True, skip_review=True)
            except StopIteration:
                pass  # Ignore StopIteration as we expect it

            assert mock_supabase_client.get_a_new_snippet_and_reserve_it.call_count >= 1
            assert mock_sleep.call_count >= 1
            mock_sleep.assert_called_with(60)  # Should sleep when no new snippets found

    def test_in_depth_analysis_no_snippets(self, mock_supabase_client, mock_s3_client):
        """Test in-depth analysis when no snippets are found"""
        mock_supabase_client.get_snippet_by_id.return_value = None

        in_depth_analysis(snippet_ids=["test-id"], repeat=False, skip_review=True)

        mock_s3_client.download_file.assert_not_called()

    @patch("processing_pipeline.stage_3.Stage3Executor.run")
    def test_process_snippet_no_disinformation_categories(
        self,
        mock_run,
        mock_supabase_client,
        sample_snippet,
        mock_gemini_response,
    ):
        """Test processing snippet without disinformation categories"""
        mock_gemini_response["disinformation_categories"] = []
        # Mock Stage3Executor.run to return a tuple (response, grounding_metadata)
        mock_run.return_value = (mock_gemini_response, "test_grounding_metadata")

        process_snippet(mock_supabase_client, sample_snippet, "test.mp3", "test-key", skip_review=False)

        # Verify the snippet was updated with empty disinformation categories
        mock_supabase_client.update_snippet.assert_called_once()
        call_kwargs = mock_supabase_client.update_snippet.call_args.kwargs
        assert call_kwargs["disinformation_categories"] == []

    @patch("google.genai.Client")
    def test_process_snippet_invalid_response(self, mock_client_class, mock_supabase_client, sample_snippet):
        """Test processing snippet with invalid Gemini response"""
        mock_audio_file = Mock()
        mock_audio_file.state.name = "PROCESSED"
        mock_audio_file.name = "test-audio-file"

        # Configure mock client
        mock_client = Mock()
        mock_client.files.upload.return_value = mock_audio_file
        mock_client.files.get.return_value = mock_audio_file
        mock_client.files.delete = Mock()

        mock_result = Mock()
        mock_result.text = "invalid json"
        mock_result.parsed = None
        mock_client.models.generate_content.return_value = mock_result

        mock_client_class.return_value = mock_client

        process_snippet(mock_supabase_client, sample_snippet, "test.mp3", "test-key", skip_review=False)

        mock_supabase_client.set_snippet_status.assert_called_with(sample_snippet["id"], "Error", mock.ANY)
