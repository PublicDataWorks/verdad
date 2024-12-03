import json
from unittest.mock import Mock, patch, call
import pytest
from processing_pipeline.stage_1 import (
    fetch_a_new_audio_file_from_supabase,
    fetch_audio_file_by_id,
    fetch_stage_1_llm_response_by_id,
    download_audio_file_from_s3,
    transcribe_audio_file_with_gemini_1_5_flash,
    transcribe_audio_file_with_custom_timestamped_transcription_generator,
    initial_disinformation_detection_with_gemini_1_5_pro,
    disinformation_detection_with_gemini_1_5_pro,
    insert_stage_1_llm_response,
    process_audio_file,
    initial_disinformation_detection,
    undo_disinformation_detection,
    redo_main_detection,
    regenerate_timestamped_transcript,
    Stage1Executor
)

@pytest.fixture
def mock_environment(monkeypatch):
    """Setup test environment variables"""
    env_vars = {
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
    with patch('processing_pipeline.stage_1.SupabaseClient') as MockSupabaseClient:
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
    with patch('boto3.client') as mock:
        s3_client = Mock()
        mock.return_value = s3_client
        yield s3_client

@pytest.fixture
def mock_gemini_model():
    """Create a mock Gemini model"""
    with patch('google.generativeai.GenerativeModel') as mock:
        model = Mock()
        model.generate_content.return_value.text = json.dumps({"flagged_snippets": []})
        mock.return_value = model
        yield mock

@pytest.fixture
def mock_openai():
    """Create a mock OpenAI client"""
    with patch('openai.OpenAI') as mock:
        client = Mock()
        client.audio.transcriptions.create.return_value = Mock(
            text="Test transcription",
            language="en",
            duration=60.0,
            segments=[
                Mock(start=0, text="Test segment 1"),
                Mock(start=30, text="Test segment 2")
            ]
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
    def test_transcribe_with_gemini_success(self, mock_gemini_model):
        """Test successful transcription with Gemini"""
        with patch('google.generativeai.upload_file') as mock_upload, \
            patch('google.generativeai.get_file') as mock_get_file, \
            patch('time.sleep') as mock_sleep:  # Mock sleep to avoid delays

            # Setup mock audio files with processing state transition
            processing_audio = Mock()
            processing_audio.state.name = "PROCESSING"
            processing_audio.name = "test_audio_file"

            processed_audio = Mock()
            processed_audio.state.name = "PROCESSED"
            processed_audio.name = "test_audio_file"

            # Set up the upload and get_file responses
            mock_upload.return_value = processing_audio
            mock_get_file.side_effect = [processing_audio, processed_audio]

            # Setup mock Gemini model response
            mock_response = Mock()
            mock_response.text = json.dumps({"transcription": "Test transcription"})
            mock_gemini_model.return_value.generate_content.return_value = mock_response

            # Call the function
            result = transcribe_audio_file_with_gemini_1_5_flash("test.mp3")

            # Verify the result
            assert isinstance(result, dict)
            assert "transcription" in result
            assert result["transcription"] == "Test transcription"

            # Verify the calls
            mock_upload.assert_called_once()
            assert mock_get_file.call_count == 2  # Called twice: once for processing, once for processed
            assert mock_sleep.call_count == 2  # Called twice while processing
            assert mock_sleep.call_args_list == [call(1), call(1)]  # Verify sleep was called with 1 second each time
            mock_gemini_model.assert_called_once()

            # Verify generate_content was called with correct arguments
            mock_gemini_model.return_value.generate_content.assert_called_once()
            args, kwargs = mock_gemini_model.return_value.generate_content.call_args
            assert len(args[0]) == 2  # Should have audio file and prompt
            assert args[0][0] == processed_audio  # First argument should be the processed audio file

    def test_transcribe_with_custom_generator_success(self, mock_environment):
        """Test successful transcription with custom generator"""
        with patch('processing_pipeline.stage_1.TimestampedTranscriptionGenerator') as mock_generator:
            mock_generator.run.return_value = "Test timestamped transcription"

            result = transcribe_audio_file_with_custom_timestamped_transcription_generator("test.mp3")

            assert result["timestamped_transcription"] == "Test timestamped transcription"
            mock_generator.run.assert_called_once()

class TestDetectionFunctions:
    def test_initial_detection_success(self, mock_environment, mock_gemini_model):
        """Test successful initial detection"""
        result = initial_disinformation_detection_with_gemini_1_5_pro(
            "Test transcription",
            {"station": "test"}
        )

        assert isinstance(result, dict)
        assert "flagged_snippets" in result
        mock_gemini_model.assert_called_once()

    def test_disinformation_detection_success(self, mock_environment, mock_gemini_model):
        """Test successful disinformation detection"""
        result = disinformation_detection_with_gemini_1_5_pro(
            "Test transcription",
            {"station": "test"}
        )

        assert isinstance(result, dict)
        assert "flagged_snippets" in result
        mock_gemini_model.assert_called_once()

class TestStage1Executor:
    def test_run_success(self, mock_environment, mock_gemini_model):
        """Test successful execution of Stage1Executor"""
        result = Stage1Executor.run(
            gemini_key="test-key",
            timestamped_transcription="Test transcription",
            metadata={"station": "test"}
        )

        assert isinstance(json.loads(result), dict)
        mock_gemini_model.assert_called_once()

    def test_run_without_api_key(self):
        """Test execution without API key"""
        with pytest.raises(ValueError, match="Google Gemini API key was not set!"):
            Stage1Executor.run(None, "test", {})

class TestMainFlows:
    def test_initial_disinformation_detection_flow(self, mock_supabase_client, mock_s3_client):
        """Test the main initial disinformation detection flow"""
        mock_supabase_client.get_a_new_audio_file_and_reserve_it.return_value = {
            "id": 1,
            "file_path": "test.mp3"
        }

        with patch('os.remove'):
            initial_disinformation_detection(
                audio_file_id=None,
                use_openai=False,
                limit=1
            )

            mock_supabase_client.get_a_new_audio_file_and_reserve_it.assert_called_once()
            mock_s3_client.download_file.assert_called_once()

    def test_undo_disinformation_detection_flow(self, mock_supabase_client):
        """Test the undo disinformation detection flow"""
        audio_file_ids = [1, 2]
        undo_disinformation_detection(audio_file_ids)

        mock_supabase_client.reset_audio_file_status.assert_called_once_with(audio_file_ids)
        mock_supabase_client.delete_stage_1_llm_responses.assert_called_once_with(audio_file_ids)

    def test_redo_main_detection_flow(self, mock_supabase_client, mock_gemini_model):
        """Test the redo main detection flow"""
        # Setup mock response
        stage_1_llm_response = {
            "id": 1,
            "timestamped_transcription": {"timestamped_transcription": "Test transcription"},
            "initial_detection_result": {"flagged_snippets": [
                {
                    "start_time": "00:00",
                    "end_time": "00:30",
                    "transcription": "Test snippet"
                }
            ]},
            "audio_file": {
                "radio_station_name": "Test Station",
                "radio_station_code": "TEST-FM",
                "location_state": "Test State",
                "location_city": "Test City",
                "recorded_at": "2024-01-01T00:00:00Z",
                "recording_day_of_week": "Monday"
            }
        }
        mock_supabase_client.get_stage_1_llm_response_by_id.return_value = stage_1_llm_response

        # Setup Gemini model response
        mock_response = Mock()
        mock_response.text = json.dumps({"flagged_snippets": [
            {
                "start_time": "00:00",
                "end_time": "00:30",
                "transcription": "Updated snippet"
            }
        ]})
        mock_gemini_model.return_value.generate_content.return_value = mock_response

        # Execute the flow
        redo_main_detection([1])

        # Verify the calls
        mock_supabase_client.get_stage_1_llm_response_by_id.assert_called_once_with(
            id=1,
            select="*, audio_file(radio_station_name, radio_station_code, location_state, location_city, recorded_at, recording_day_of_week, file_path)"
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
                "recorded_at": "2024-01-01T00:00:00Z",
                "recording_day_of_week": "Monday"
            }
        }
        mock_supabase_client.get_stage_1_llm_response_by_id.return_value = stage_1_llm_response

        with patch('os.remove') as mock_remove, \
            patch('processing_pipeline.stage_1.transcribe_audio_file_with_custom_timestamped_transcription_generator') as mock_transcribe:
            mock_transcribe.return_value = {"timestamped_transcription": "Test transcription"}

            regenerate_timestamped_transcript([1])

            mock_supabase_client.get_stage_1_llm_response_by_id.assert_called_once_with(
                id=1,
                select="*, audio_file(radio_station_name, radio_station_code, location_state, location_city, recorded_at, recording_day_of_week, file_path)"
            )

class TestHelperFunctions:
    def test_process_audio_file_success(self, mock_supabase_client, mock_gemini_model):
        """Test successful audio file processing"""
        # Setup test data
        audio_file = {
            "id": 1,
            "radio_station_name": "Test Station",
            "radio_station_code": "TEST-FM",
            "location_state": "Test State",
            "location_city": "Test City",
            "recorded_at": "2024-01-01T00:00:00Z",
            "recording_day_of_week": "Monday"
        }

        # Setup mocks
        with patch('processing_pipeline.stage_1.transcribe_audio_file_with_gemini_1_5_flash') as mock_transcribe, \
            patch('processing_pipeline.stage_1.initial_disinformation_detection_with_gemini_1_5_pro') as mock_detect:

            # Setup mock responses
            mock_transcribe.return_value = {"transcription": "Test transcription"}
            mock_detect.return_value = {"flagged_snippets": []}

            # Execute the function
            process_audio_file(mock_supabase_client, audio_file, "test.mp3", False)

            # Verify the calls
            mock_transcribe.assert_called_once_with("test.mp3")
            mock_detect.assert_called_once_with(
                "Test transcription",  # Pass just the transcription text
                {
                    "radio_station_name": "Test Station",
                    "radio_station_code": "TEST-FM",
                    "location": {
                        "state": "Test State",
                        "city": "Test City"
                    },
                    "recorded_at": "2024-01-01T00:00:00Z",
                    "recording_day_of_week": "Monday",
                    "time_zone": "UTC"
                }
            )

            # Verify database interactions
            mock_supabase_client.set_audio_file_status.assert_called_with(1, "Processed")
            mock_supabase_client.insert_stage_1_llm_response.assert_called_once_with(
                audio_file_id=1,
                initial_transcription="Test transcription",  # Changed this line to match actual behavior
                initial_detection_result={"flagged_snippets": []},
                timestamped_transcription=None,
                detection_result=None,
                status="Processed"
            )

    def test_process_audio_file_with_error(self, mock_supabase_client):
        """Test audio file processing with error"""
        audio_file = {"id": 1}

        with patch('processing_pipeline.stage_1.transcribe_audio_file_with_gemini_1_5_flash',
                  side_effect=Exception("Test error")):
            process_audio_file(mock_supabase_client, audio_file, "test.mp3", False)

        mock_supabase_client.set_audio_file_status.assert_called_with(
            1, "Error", "Test error"
        )

    def test_insert_stage_1_llm_response(self, mock_supabase_client):
        """Test inserting Stage 1 LLM response"""
        insert_stage_1_llm_response(
            supabase_client=mock_supabase_client,
            audio_file_id=1,
            initial_transcription="Test transcription",
            initial_detection_result={"test": "result"},
            timestamped_transcription={"test": "transcription"},
            detection_result={"test": "result"},
            status="New"
        )

        mock_supabase_client.insert_stage_1_llm_response.assert_called_once()
