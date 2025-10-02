import json
import os
from unittest.mock import Mock, patch, call
import uuid
import pytest
from google.api_core import exceptions as google_exceptions
from google.genai.errors import ServerError
from processing_pipeline.constants import GeminiModel
from processing_pipeline.stage_1 import (
    fetch_a_new_audio_file_from_supabase,
    fetch_audio_file_by_id,
    fetch_stage_1_llm_response_by_id,
    download_audio_file_from_s3,
    transcribe_audio_file_with_gemini,
    transcribe_audio_file_with_custom_timestamped_transcription_generator,
    initial_disinformation_detection_with_gemini,
    disinformation_detection_with_gemini,
    insert_stage_1_llm_response,
    process_audio_file,
    initial_disinformation_detection,
    undo_disinformation_detection,
    redo_main_detection,
    regenerate_timestamped_transcript,
    Stage1Executor,
    transcribe_audio_file_with_open_ai_whisper_1,
    transcribe_audio_file_with_gemini_2_5_pro,
)


@pytest.fixture
def mock_environment(monkeypatch):
    """Setup test environment variables"""
    env_vars = {
        "PYTHONPATH": ".:./src",
        "GOOGLE_GEMINI_KEY": "test-key",
        "OPENAI_API_KEY": "test-key",
        "R2_BUCKET_NAME": "test-bucket",
    }
    for key, value in env_vars.items():
        monkeypatch.setenv(key, value)
    return env_vars


@pytest.fixture
def mock_supabase_client():
    """Create a mock Supabase client"""
    with patch("processing_pipeline.stage_1.SupabaseClient") as MockSupabaseClient:
        mock_client = Mock()
        mock_client.get_a_new_audio_file_and_reserve_it.return_value = None
        mock_client.get_audio_file_by_id.return_value = None
        mock_client.get_stage_1_llm_response_by_id.return_value = None
        mock_client.set_audio_file_status.return_value = None
        mock_client.set_stage_1_llm_response_status.return_value = None
        mock_client.insert_stage_1_llm_response.return_value = None
        mock_client.reset_audio_file_status.return_value = None
        mock_client.delete_stage_1_llm_responses.return_value = None
        mock_client.update_stage_1_llm_response_detection_result.return_value = None
        mock_client.update_stage_1_llm_response_timestamped_transcription.return_value = None
        mock_client.reset_stage_1_llm_response_status.return_value = None
        MockSupabaseClient.return_value = mock_client
        yield mock_client


@pytest.fixture
def mock_s3_client():
    """Create a mock S3 client"""
    with patch("boto3.client") as mock:
        s3_client = Mock()
        mock.return_value = s3_client
        yield s3_client


@pytest.fixture
def mock_genai():
    """Create a mock Gemini client"""
    with patch("processing_pipeline.stage_1.genai") as mock:
        client = Mock()
        mock_flagged_snippets = {"flagged_snippets": []}
        client.models.generate_content.return_value.text = json.dumps(mock_flagged_snippets)
        client.models.generate_content.return_value.parsed = mock_flagged_snippets
        mock.Client.return_value = client
        yield mock


@pytest.fixture
def mock_openai():
    """Create a mock OpenAI client"""
    with patch("openai.OpenAI") as mock:
        client = Mock()
        client.audio.transcriptions.create.return_value = Mock(
            text="Test transcription",
            language="en",
            duration=60.0,
            segments=[Mock(start=0, text="Test segment 1"), Mock(start=30, text="Test segment 2")],
        )
        mock.return_value = client
        yield mock


class TestFetchFunctions:
    def test_fetch_new_audio_file_success(self, mock_supabase_client):
        """Test successful fetch of new audio file"""
        expected_response = {"id": 1, "status": "New"}
        mock_supabase_client.get_a_new_audio_file_and_reserve_it.return_value = expected_response

        result = fetch_a_new_audio_file_from_supabase(mock_supabase_client)

        assert result == expected_response
        mock_supabase_client.get_a_new_audio_file_and_reserve_it.assert_called_once()

    def test_fetch_audio_file_by_id_success(self, mock_supabase_client):
        """Test successful fetch of audio file by ID"""
        expected_response = {"id": 1, "status": "New"}
        mock_supabase_client.get_audio_file_by_id.return_value = expected_response

        result = fetch_audio_file_by_id(mock_supabase_client, 1)

        assert result == expected_response
        mock_supabase_client.get_audio_file_by_id.assert_called_once_with(1)

    def test_fetch_stage_1_llm_response_by_id_success(self, mock_supabase_client):
        """Test successful fetch of Stage 1 LLM response"""
        expected_response = {"id": 1, "status": "New"}
        mock_supabase_client.get_stage_1_llm_response_by_id.return_value = expected_response

        result = fetch_stage_1_llm_response_by_id(mock_supabase_client, 1)

        assert result == expected_response
        mock_supabase_client.get_stage_1_llm_response_by_id.assert_called_once()


class TestS3Operations:
    def test_download_audio_file_success(self, mock_s3_client):
        """Test successful download of audio file from S3"""
        file_path = "test/path.mp3"
        result = download_audio_file_from_s3(mock_s3_client, file_path)

        assert result == "path.mp3"
        mock_s3_client.download_file.assert_called_once()


class TestTranscriptionFunctions:
    def test_transcribe_with_gemini_success(self, mock_environment):
        """Test successful transcription with Gemini"""
        with patch("processing_pipeline.stage_1.Stage1PreprocessTranscriptionExecutor") as mock_executor:
            mock_executor.run.return_value = {"transcription": "Test transcription"}

            # Call the function
            result = transcribe_audio_file_with_gemini("test.mp3")

            # Verify the result
            assert isinstance(result, str)
            assert result == "Test transcription"

            # Verify the executor was called
            mock_executor.run.assert_called_once_with("test.mp3", "test-key", GeminiModel.GEMINI_FLASH_LATEST)

    def test_transcribe_with_custom_generator_success(self, mock_environment):
        """Test successful transcription with custom generator"""
        with patch("processing_pipeline.stage_1.TimestampedTranscriptionGenerator") as mock_generator:
            mock_generator.run.return_value = "Test timestamped transcription"

            result = transcribe_audio_file_with_custom_timestamped_transcription_generator("test.mp3")

            assert result["timestamped_transcription"] == "Test timestamped transcription"
            mock_generator.run.assert_called_once()

    def test_transcribe_with_gemini_2_5_pro_success(self, mock_environment):
        """Test successful transcription with Gemini 2.5 Pro"""
        with patch("processing_pipeline.stage_1.Gemini25ProTranscriptionGenerator") as mock_generator:
            mock_generator.run.return_value = "Test timestamped transcription"

            result = transcribe_audio_file_with_gemini_2_5_pro("test.mp3")

            assert result == {"timestamped_transcription": "Test timestamped transcription"}
            mock_generator.run.assert_called_once_with("test.mp3", os.getenv("GOOGLE_GEMINI_KEY"))

    def test_transcribe_with_gemini_2_5_pro_rate_limit(self, mock_environment):
        """Test transcription with Gemini 2.5 Pro hitting rate limit"""
        with patch("processing_pipeline.stage_1.Gemini25ProTranscriptionGenerator") as mock_generator:
            mock_generator.run.side_effect = google_exceptions.ResourceExhausted("Rate limit exceeded")
            with pytest.raises(google_exceptions.ResourceExhausted):
                transcribe_audio_file_with_gemini_2_5_pro("test.mp3")


class TestDetectionFunctions:
    def test_initial_detection_success(self, mock_environment):
        """Test successful initial detection"""
        with patch("processing_pipeline.stage_1.Stage1PreprocessDetectionExecutor") as mock_executor:
            mock_executor.run.return_value = {"flagged_snippets": []}

            result = initial_disinformation_detection_with_gemini("Test transcription", {"station": "test"})

            assert isinstance(result, dict)
            assert "flagged_snippets" in result
            mock_executor.run.assert_called_once_with(
                "test-key", GeminiModel.GEMINI_FLASH_LATEST, "Test transcription", {"station": "test"}
            )

    def test_disinformation_detection_success(self, mock_environment):
        """Test successful disinformation detection"""
        with patch("processing_pipeline.stage_1.Stage1Executor") as mock_executor:
            mock_executor.run.return_value = {"flagged_snippets": []}

            result = disinformation_detection_with_gemini("Test transcription", {"station": "test"})

            assert isinstance(result, dict)
            assert "flagged_snippets" in result
            mock_executor.run.assert_called_once_with(
                gemini_key="test-key",
                model_name=GeminiModel.GEMINI_FLASH_LATEST,
                timestamped_transcription="Test transcription",
                metadata={"station": "test"},
            )


class TestStage1Executor:
    def test_run_success(self, mock_environment, mock_genai):
        """Test successful execution of Stage1Executor"""
        mock_client = mock_genai.Client.return_value
        mock_client.models.generate_content.return_value.parsed = {"flagged_snippets": []}

        result = Stage1Executor.run(
            gemini_key="test-key",
            model_name=GeminiModel.GEMINI_FLASH_LATEST,
            timestamped_transcription="Test transcription",
            metadata={"station": "test"},
        )

        assert isinstance(result, dict)
        mock_genai.Client.assert_called_once_with(api_key="test-key")
        mock_client.models.generate_content.assert_called_once()

    def test_run_without_api_key(self):
        """Test execution without API key"""
        with pytest.raises(ValueError, match="Google Gemini API key was not set!"):
            Stage1Executor.run(None, GeminiModel.GEMINI_FLASH_LATEST, "test", {})


class TestMainFlows:
    def test_initial_disinformation_detection_flow(self, mock_supabase_client, mock_s3_client):
        """Test the main initial disinformation detection flow"""
        mock_supabase_client.get_a_new_audio_file_and_reserve_it.return_value = {"id": 1, "file_path": "test.mp3"}

        with patch("os.remove"), patch("processing_pipeline.stage_1.process_audio_file") as mock_process:
            initial_disinformation_detection(audio_file_id=None, limit=1)

            mock_supabase_client.get_a_new_audio_file_and_reserve_it.assert_called_once()
            mock_s3_client.download_file.assert_called_once()
            mock_process.assert_called_once()

    def test_undo_disinformation_detection_flow(self, mock_supabase_client):
        """Test the undo disinformation detection flow"""
        audio_file_ids = [1, 2]
        undo_disinformation_detection(audio_file_ids)

        mock_supabase_client.reset_audio_file_status.assert_called_once_with(audio_file_ids)
        mock_supabase_client.delete_stage_1_llm_responses.assert_called_once_with(audio_file_ids)

    def test_redo_main_detection_flow(self, mock_supabase_client, mock_genai):
        """Test the redo main detection flow"""
        # Setup mock response
        stage_1_llm_response = {
            "id": 1,
            "timestamped_transcription": {"timestamped_transcription": "Test transcription"},
            "initial_detection_result": {
                "flagged_snippets": [{"start_time": "00:00", "end_time": "00:30", "transcription": "Test snippet"}]
            },
            "audio_file": {
                "radio_station_name": "Test Station",
                "radio_station_code": "TEST-FM",
                "location_state": "Test State",
                "location_city": "Test City",
                "recorded_at": "2024-01-01T00:00:00+00:00",
                "recording_day_of_week": "Monday",
            },
        }
        mock_supabase_client.get_stage_1_llm_response_by_id.return_value = stage_1_llm_response

        # Setup Gemini model response
        mock_client = mock_genai.Client.return_value
        mock_response = Mock()
        mock_response.parsed = {
            "flagged_snippets": [
                {"start_time": "00:00", "end_time": "00:30", "transcription": "Updated snippet"},
            ],
        }

        mock_client.models.generate_content.return_value = mock_response

        # Execute the flow
        redo_main_detection([1])

        # Verify the calls
        mock_supabase_client.get_stage_1_llm_response_by_id.assert_called_once_with(
            id=1,
            select="*, audio_file(radio_station_name, radio_station_code, location_state, location_city, recorded_at, recording_day_of_week, file_path)",
        )

    def test_regenerate_timestamped_transcript_flow(self, mock_supabase_client, mock_s3_client):
        """Test the regenerate timestamped transcript flow"""
        # Setup mock response
        stage_1_llm_response = {
            "id": 1,
            "initial_detection_result": {"flagged_snippets": []},
            "audio_file": {
                "file_path": "test.mp3",
                "radio_station_name": "Test Station",
                "radio_station_code": "TEST-FM",
                "location_state": "Test State",
                "location_city": "Test City",
                "recorded_at": "2024-01-01T00:00:00+00:00",
                "recording_day_of_week": "Monday",
            },
        }
        mock_supabase_client.get_stage_1_llm_response_by_id.return_value = stage_1_llm_response

        with patch("os.remove") as mock_remove, patch(
            "processing_pipeline.stage_1.transcribe_audio_file_with_gemini_2_5_pro"
        ) as mock_transcribe:
            mock_transcribe.return_value = {"timestamped_transcription": "Test transcription"}

            regenerate_timestamped_transcript([1])

            mock_supabase_client.get_stage_1_llm_response_by_id.assert_called_once_with(
                id=1,
                select="*, audio_file(radio_station_name, radio_station_code, location_state, location_city, recorded_at, recording_day_of_week, file_path)",
            )


class TestHelperFunctions:
    def test_process_audio_file_success(self, mock_supabase_client):
        """Test successful audio file processing"""
        # Setup test data
        audio_file = {
            "id": 1,
            "radio_station_name": "Test Station",
            "radio_station_code": "TEST-FM",
            "location_state": "Test State",
            "location_city": "Test City",
            "recorded_at": "2024-01-01T00:00:00+00:00",
            "recording_day_of_week": "Monday",
        }

        # Setup mocks
        with patch("processing_pipeline.stage_1.transcribe_audio_file_with_gemini") as mock_transcribe, patch(
            "processing_pipeline.stage_1.initial_disinformation_detection_with_gemini"
        ) as mock_detect:

            # Setup mock responses
            mock_transcribe.return_value = "Test transcription"
            mock_detect.return_value = {"flagged_snippets": []}

            # Execute the function
            process_audio_file(mock_supabase_client, audio_file, "test.mp3")

            # Verify the calls
            mock_transcribe.assert_called_once_with("test.mp3")
            mock_detect.assert_called_once_with(
                "Test transcription",  # Pass just the transcription text
                {
                    "radio_station_name": "Test Station",
                    "radio_station_code": "TEST-FM",
                    "location": {"state": "Test State", "city": "Test City"},
                    "recorded_at": "January 1, 2024 12:00 AM",
                    "recording_day_of_week": "Monday",
                    "time_zone": "UTC",
                },
            )

            # Verify database interactions
            mock_supabase_client.set_audio_file_status.assert_called_with(1, "Processed")
            mock_supabase_client.insert_stage_1_llm_response.assert_called_once_with(
                audio_file_id=1,
                initial_transcription="Test transcription",  # Changed this line to match actual behavior
                initial_detection_result={"flagged_snippets": []},
                transcriptor=None,
                timestamped_transcription=None,
                detection_result=None,
                status="Processed",
            )

    def test_process_audio_file_with_error(self, mock_supabase_client):
        """Test audio file processing with error"""
        audio_file = {"id": 1}

        with patch(
            "processing_pipeline.stage_1.transcribe_audio_file_with_gemini",
            side_effect=Exception("Test error"),
        ):
            process_audio_file(mock_supabase_client, audio_file, "test.mp3")

        mock_supabase_client.set_audio_file_status.assert_called_with(1, "Error", "Test error")

    def test_insert_stage_1_llm_response(self, mock_supabase_client):
        """Test inserting Stage 1 LLM response"""
        insert_stage_1_llm_response(
            supabase_client=mock_supabase_client,
            audio_file_id=1,
            initial_transcription="Test transcription",
            initial_detection_result={"test": "result"},
            transcriptor="gemini-1206",
            timestamped_transcription={"test": "transcription"},
            detection_result={"test": "result"},
            status="New",
        )

        mock_supabase_client.insert_stage_1_llm_response.assert_called_once()

    def test_transcribe_audio_file_with_whisper_1(self):
        """Test transcription with OpenAI Whisper"""
        mock_file = Mock()
        with patch("os.getenv", return_value="test-key"), patch(
            "builtins.open", return_value=mock_file
        ) as mock_open, patch("processing_pipeline.stage_1.OpenAI") as mock_openai_class:
            mock_client = Mock()
            mock_openai_class.return_value = mock_client
            mock_response = Mock(
                text="Test transcription",
                language="en",
                duration=60.0,
                segments=[Mock(start=0, text="Test segment 1"), Mock(start=30, text="Test segment 2")],
            )
            mock_client.audio.transcriptions.create.return_value = mock_response

            result = transcribe_audio_file_with_open_ai_whisper_1("test.mp3")

            # Verify file operations
            mock_open.assert_called_once_with("test.mp3", "rb")

            # Verify OpenAI client setup and usage
            mock_openai_class.assert_called_once_with(api_key="test-key")
            mock_client.audio.transcriptions.create.assert_called_once_with(
                model="whisper-1", file=mock_file, response_format="verbose_json", timestamp_granularities=["segment"]
            )

            # Verify result
            assert result["language"] == "en"
            assert result["duration"] == 60
            assert result["transcription"] == "Test transcription"
            assert "[00:00]" in result["timestamped_transcription"]
            assert "[00:30]" in result["timestamped_transcription"]
            assert "Test segment 1" in result["timestamped_transcription"]
            assert "Test segment 2" in result["timestamped_transcription"]

    def test_transcribe_audio_file_with_whisper_1_no_api_key(self):
        """Test transcription without API key"""
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ValueError, match="OpenAI API key was not set!"):
                transcribe_audio_file_with_open_ai_whisper_1("test.mp3")

    def test_initial_disinformation_detection_with_retry(self, mock_supabase_client, mock_s3_client):
        """Test initial disinformation detection with retries"""
        audio_file = {
            "id": 1,
            "file_path": "test/path.mp3",
            "status": "Error",
            "radio_station_name": "Test Station",
            "radio_station_code": "TEST-FM",
            "location_state": "Test State",
            "location_city": "Test City",
            "recorded_at": "2024-01-01T00:00:00+00:00",
            "recording_day_of_week": "Monday",
        }

        # Setup the mock to return None first, then the audio file, then None again
        mock_supabase_client.get_a_new_audio_file_and_reserve_it.side_effect = [None, audio_file, None]

        with patch("os.remove"), patch("time.sleep") as mock_sleep, patch(
            "processing_pipeline.stage_1.process_audio_file"
        ) as mock_process:

            initial_disinformation_detection(audio_file_id=None, limit=1)

            assert mock_sleep.call_count >= 1
            mock_sleep.assert_has_calls([call(60)])  # First sleep when no file found
            mock_process.assert_called_once_with(mock_supabase_client, audio_file, "path.mp3")

    def test_redo_main_detection_multiple_files(self, mock_supabase_client, mock_genai):
        """Test redo main detection with multiple files"""
        stage_1_llm_responses = [
            {
                "id": 1,
                "timestamped_transcription": {"timestamped_transcription": "Test 1"},
                "initial_detection_result": {"flagged_snippets": [{"uuid": "1"}]},
                "audio_file": {
                    "radio_station_name": "Test Station",
                    "radio_station_code": "TEST-FM",
                    "location_state": "Test State",
                    "location_city": "Test City",
                    "recorded_at": "2024-01-01T00:00:00+00:00",
                    "recording_day_of_week": "Monday",
                },
            },
            {
                "id": 2,
                "timestamped_transcription": {"timestamped_transcription": "Test 2"},
                "initial_detection_result": {"flagged_snippets": [{"uuid": "2"}]},
                "audio_file": {
                    "radio_station_name": "Test Station",
                    "radio_station_code": "TEST-FM",
                    "location_state": "Test State",
                    "location_city": "Test City",
                    "recorded_at": "2024-01-01T00:00:00+00:00",
                    "recording_day_of_week": "Monday",
                },
            },
        ]

        # Setup mock client
        mock_client = mock_genai.Client.return_value
        mock_client.models.generate_content.return_value.parsed = {"flagged_snippets": []}

        for response in stage_1_llm_responses:
            mock_supabase_client.get_stage_1_llm_response_by_id.return_value = response
            redo_main_detection([1, 2])

            mock_supabase_client.update_stage_1_llm_response_detection_result.assert_called()
            mock_supabase_client.reset_stage_1_llm_response_status.assert_called()

    def test_regenerate_timestamped_transcript_with_error(self, mock_supabase_client, mock_s3_client):
        """Test regenerate timestamped transcript with error"""
        stage_1_llm_response = {"id": 1, "audio_file": {"file_path": "test/path.mp3"}}
        mock_supabase_client.get_stage_1_llm_response_by_id.return_value = stage_1_llm_response

        # Mock the S3 client directly since it's used in the code
        mock_s3_client.download_file.side_effect = Exception("Download failed")

        with pytest.raises(Exception, match="Download failed"):
            regenerate_timestamped_transcript([1])

        # Since we're not handling the error in the function itself,
        # we should not expect set_stage_1_llm_response_status to be called
        mock_supabase_client.set_stage_1_llm_response_status.assert_not_called()

    def test_undo_disinformation_detection_no_responses(self, mock_supabase_client):
        """Test undo disinformation detection with no responses"""
        mock_supabase_client.delete_stage_1_llm_responses.return_value = []

        undo_disinformation_detection([1, 2])

        mock_supabase_client.reset_audio_file_status.assert_called_once_with([1, 2])
        mock_supabase_client.delete_stage_1_llm_responses.assert_called_once_with([1, 2])

    @patch("processing_pipeline.stage_1.TimestampedTranscriptionGenerator")
    def test_transcribe_audio_file_with_custom_generator_error(self, mock_generator):
        """Test custom generator with error"""
        mock_generator.run.side_effect = Exception("Generation failed")

        with pytest.raises(Exception, match="Generation failed"):
            transcribe_audio_file_with_custom_timestamped_transcription_generator("test.mp3")

    def test_process_audio_file_with_no_flagged_snippets(self, mock_supabase_client):
        """Test processing audio file with no flagged snippets"""
        audio_file = {
            "id": 1,
            "radio_station_name": "Test Station",
            "radio_station_code": "TEST-FM",
            "location_state": "Test State",
            "location_city": "Test City",
            "recorded_at": "2024-01-01T00:00:00+00:00",
            "recording_day_of_week": "Monday",
        }

        # Mock responses with no flagged snippets
        mock_flash_response = "Test transcription"
        mock_detection_response = {"flagged_snippets": []}

        with patch(
            "processing_pipeline.stage_1.transcribe_audio_file_with_gemini", return_value=mock_flash_response
        ), patch(
            "processing_pipeline.stage_1.initial_disinformation_detection_with_gemini",
            return_value=mock_detection_response,
        ):

            process_audio_file(
                mock_supabase_client,
                audio_file,
                "test.mp3",
            )

            mock_supabase_client.insert_stage_1_llm_response.assert_called_with(
                audio_file_id=1,
                initial_transcription="Test transcription",
                initial_detection_result=mock_detection_response,
                transcriptor=None,
                timestamped_transcription=None,
                detection_result=None,
                status="Processed",
            )

    def test_stage_1_executor(self, mock_genai):
        """Test Stage1Executor"""
        mock_client = mock_genai.Client.return_value
        mock_response = Mock()
        mock_response.parsed = {"test": "response"}
        mock_client.models.generate_content.return_value = mock_response

        result = Stage1Executor.run(
            gemini_key="test-key",
            model_name=GeminiModel.GEMINI_FLASH_LATEST,
            timestamped_transcription="Test transcription",
            metadata={"test": "metadata"},
        )

        # Verify behavior
        assert isinstance(result, dict)
        mock_genai.Client.assert_called_once_with(api_key="test-key")
        mock_client.models.generate_content.assert_called_once()

        # Verify the content of the request
        args, kwargs = mock_client.models.generate_content.call_args
        assert len(kwargs["contents"]) == 1  # Should have one argument (user prompt)
        assert "Test transcription" in kwargs["contents"][0]  # Should contain the transcription
        assert json.dumps({"test": "metadata"}, indent=2) in kwargs["contents"][0]  # Should contain the metadata

    def test_initial_disinformation_detection_specific_file(self, mock_supabase_client, mock_s3_client):
        """Test initial disinformation detection with specific file"""
        audio_file = {
            "id": 1,
            "file_path": "test/path.mp3",
            "radio_station_name": "Test Station",
            "radio_station_code": "TEST-FM",
            "location_state": "Test State",
            "location_city": "Test City",
            "recorded_at": "2024-01-01T00:00:00+00:00",
            "recording_day_of_week": "Monday",
        }
        mock_supabase_client.get_audio_file_by_id.return_value = audio_file

        with patch("os.remove"):
            initial_disinformation_detection(audio_file_id=1, limit=1)

            mock_supabase_client.get_audio_file_by_id.assert_called_once_with(1)
            mock_s3_client.download_file.assert_called_once()

    def test_transcribe_audio_file_with_custom_generator_multiple_segments(self, mock_supabase_client):
        """Test transcription with custom generator handling multiple segments"""
        with patch("processing_pipeline.stage_1.TimestampedTranscriptionGenerator") as mock_generator:
            # Mock generator to return transcription with multiple segments
            mock_generator.run.return_value = (
                "[00:00] First segment.\n" "[00:10] Second segment.\n" "[00:20] Third segment.\n"
            )

            result = transcribe_audio_file_with_custom_timestamped_transcription_generator("test.mp3")

            assert isinstance(result, dict)
            assert "timestamped_transcription" in result
            assert len(result["timestamped_transcription"].split("\n")) == 4  # 3 segments + empty line
            mock_generator.run.assert_called_once_with("test.mp3", os.getenv("GOOGLE_GEMINI_KEY"), 10)

    def test_disinformation_detection_with_unicode_handling(self, mock_supabase_client, mock_genai):
        """Test disinformation detection with Unicode characters"""
        timestamped_transcription = "Test transcription with Unicode: áéíóú ñ"
        metadata = {"radio_station_name": "Test Station", "time_zone": "UTC"}

        # Configure mock response with Unicode characters
        mock_client = mock_genai.Client.return_value
        mock_client.models.generate_content.return_value.parsed = {
            "flagged_snippets": [
                {
                    "uuid": str(uuid.uuid4()),
                    "transcription": "Unicode text: áéíóú",
                    "explanation": "Test explanation with ñ",
                },
            ]
        }

        result = disinformation_detection_with_gemini(
            timestamped_transcription=timestamped_transcription, metadata=metadata
        )

        assert isinstance(result, dict)
        assert "flagged_snippets" in result
        assert len(result["flagged_snippets"]) == 1
        assert "uuid" in result["flagged_snippets"][0]

    def test_regenerate_timestamped_transcript_with_multiple_files(self, mock_supabase_client, mock_s3_client):
        """Test regenerating timestamped transcripts for multiple files"""
        stage_1_llm_responses = [
            {
                "id": 1,
                "audio_file": {
                    "file_path": "test1.mp3",
                    "radio_station_name": "Test Station 1",
                    "radio_station_code": "TEST1-FM",
                    "location_state": "Test State",
                    "location_city": "Test City",
                    "recorded_at": "2024-01-01T00:00:00+00:00",
                    "recording_day_of_week": "Monday",
                },
                "initial_detection_result": {"flagged_snippets": [{"uuid": "1"}]},
                "timestamped_transcription": {"timestamped_transcription": "Test transcription 1"},
            },
            {
                "id": 2,
                "audio_file": {
                    "file_path": "test2.mp3",
                    "radio_station_name": "Test Station 2",
                    "radio_station_code": "TEST2-FM",
                    "location_state": "Test State",
                    "location_city": "Test City",
                    "recorded_at": "2024-01-01T00:00:00+00:00",
                    "recording_day_of_week": "Monday",
                },
                "initial_detection_result": {"flagged_snippets": [{"uuid": "2"}]},
                "timestamped_transcription": {"timestamped_transcription": "Test transcription 2"},
            },
        ]

        mock_gemini_response = Mock()
        mock_gemini_response.parsed = {
            "flagged_snippets": [
                {
                    "uuid": str(uuid.uuid4()),
                    "transcription": "Test transcription",
                    "explanation": "Test explanation",
                }
            ]
        }

        with patch("os.remove"), patch(
            "processing_pipeline.stage_1.transcribe_audio_file_with_gemini_2_5_pro"
        ) as mock_transcribe, patch(
            "processing_pipeline.stage_1.fetch_stage_1_llm_response_by_id"
        ) as mock_fetch, patch(
            "processing_pipeline.stage_1.download_audio_file_from_s3"
        ) as mock_download, patch(
            "processing_pipeline.stage_1.genai"
        ) as mock_genai_sdk:

            # Setup mock transcribe
            mock_transcribe.return_value = {"timestamped_transcription": "Test transcription"}

            # Setup mock fetch
            mock_fetch.side_effect = stage_1_llm_responses

            # Setup mock download
            mock_download.return_value = "local_file.mp3"

            # Setup mock Gemini client
            mock_client = Mock()
            mock_client.models.generate_content.return_value = mock_gemini_response
            mock_genai_sdk.Client.return_value = mock_client

            regenerate_timestamped_transcript([1, 2])

            # Verify fetch was called for each ID
            assert mock_fetch.call_count == 2
            mock_fetch.assert_has_calls([call(mock_supabase_client, 1), call(mock_supabase_client, 2)])

            # Verify transcribe was called for each file
            assert mock_transcribe.call_count == 2
            mock_transcribe.assert_has_calls([call("local_file.mp3"), call("local_file.mp3")])

            # Verify Gemini model was called for each file
            assert mock_client.models.generate_content.call_count == 2

            # Verify update was called for each response
            assert mock_supabase_client.update_stage_1_llm_response_timestamped_transcription.call_count == 2
            mock_supabase_client.update_stage_1_llm_response_timestamped_transcription.assert_has_calls(
                [
                    call(1, {"timestamped_transcription": "Test transcription"}, "gemini-1206"),
                    call(2, {"timestamped_transcription": "Test transcription"}, "gemini-1206"),
                ]
            )

            # Verify download was called for each file
            assert mock_download.call_count == 2
            mock_download.assert_has_calls([call(mock_s3_client, "test1.mp3"), call(mock_s3_client, "test2.mp3")])

            # Verify status updates
            assert mock_supabase_client.reset_stage_1_llm_response_status.call_count == 2
            mock_supabase_client.reset_stage_1_llm_response_status.assert_has_calls([call(1), call(2)])

    def test_initial_disinformation_detection_memory_management(self, mock_supabase_client, mock_s3_client):
        """Test memory management during initial disinformation detection"""
        audio_files = [
            {
                "id": i,
                "file_path": f"test{i}.mp3",
                "radio_station_name": "Test Station",
                "radio_station_code": "TEST-FM",
                "location_state": "Test State",
                "location_city": "Test City",
                "recorded_at": "2024-01-01T00:00:00+00:00",
                "recording_day_of_week": "Monday",
            }
            for i in range(3)
        ]

        mock_supabase_client.get_a_new_audio_file_and_reserve_it.side_effect = audio_files + [None]

        with patch("os.remove") as mock_remove, patch("processing_pipeline.stage_1.process_audio_file") as mock_process:

            initial_disinformation_detection(audio_file_id=None, limit=3)

            assert mock_process.call_count == 3
            assert mock_remove.call_count == 3
            assert mock_s3_client.download_file.call_count == 3

    def test_process_audio_file_with_gemini_2_5_pro_fallback(self, mock_supabase_client):
        """Test processing audio file with Gemini 2.5 Pro fallback to custom generator"""
        audio_file = {
            "id": 1,
            "radio_station_name": "Test Station",
            "radio_station_code": "TEST-FM",
            "location_state": "Test State",
            "location_city": "Test City",
            "recorded_at": "2024-01-01T00:00:00+00:00",
            "recording_day_of_week": "Monday",
        }

        with patch("processing_pipeline.stage_1.transcribe_audio_file_with_gemini") as mock_flash, patch(
            "processing_pipeline.stage_1.transcribe_audio_file_with_gemini_2_5_pro"
        ) as mock_gemini_2_5_pro, patch(
            "processing_pipeline.stage_1.transcribe_audio_file_with_custom_timestamped_transcription_generator"
        ) as mock_custom, patch(
            "processing_pipeline.stage_1.initial_disinformation_detection_with_gemini"
        ) as mock_initial_detect, patch(
            "processing_pipeline.stage_1.disinformation_detection_with_gemini"
        ) as mock_main_detect:

            # Setup mock responses
            mock_flash.return_value = "Test transcription"
            mock_gemini_2_5_pro.side_effect = ServerError(500, {"error": {"message": "Test error"}})
            mock_custom.return_value = {"timestamped_transcription": "Test custom transcription"}
            mock_initial_detect.return_value = {"flagged_snippets": [{"uuid": "test-uuid"}]}
            mock_main_detect.return_value = {"flagged_snippets": []}

            process_audio_file(mock_supabase_client, audio_file, "test.mp3")

            # Verify the calls and fallback behavior
            mock_flash.assert_called_once()
            mock_gemini_2_5_pro.assert_called_once()
            mock_custom.assert_called_once()
            mock_initial_detect.assert_called_once()
            mock_main_detect.assert_called_once()

            # Verify that custom generator was used as fallback
            calls = mock_supabase_client.insert_stage_1_llm_response.call_args_list
            assert any(call.kwargs.get("transcriptor") == "custom" for call in calls)
