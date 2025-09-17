import json
from unittest.mock import Mock, patch
import pytest
from google.genai.types import HarmCategory, HarmBlockThreshold
from processing_pipeline.stage_1_preprocess import (
    Stage1PreprocessTranscriptionExecutor,
    Stage1PreprocessDetectionExecutor
)
from processing_pipeline.constants import GEMINI_2_5_FLASH, GEMINI_2_5_PRO

class TestStage1PreprocessTranscriptionExecutor:
    @pytest.fixture
    def mock_genai(self):
        with patch('processing_pipeline.stage_1_preprocess.genai') as mock:
            # Mock Client and its methods
            mock_client = Mock()
            mock.Client.return_value = mock_client
            yield mock

    @pytest.fixture
    def mock_audio_file(self):
        mock = Mock()
        mock.state.name = "PROCESSED"
        mock.name = "test_audio_file"
        return mock

    def test_run_success(self, mock_genai, mock_audio_file):
        """Test successful transcription execution"""
        # Setup mock client and response
        mock_client = mock_genai.Client.return_value
        mock_client.files.upload.return_value = mock_audio_file
        mock_client.files.get.return_value = mock_audio_file

        mock_result = Mock()
        mock_result.text = json.dumps({"transcription": "Test transcription"})
        mock_client.models.generate_content.return_value = mock_result

        # Run the executor
        result = Stage1PreprocessTranscriptionExecutor.run("test.mp3", "fake-api-key")

        # Verify client creation
        mock_genai.Client.assert_called_once_with(api_key="fake-api-key")

        # Verify file operations
        mock_client.files.upload.assert_called_once_with(file="test.mp3")
        mock_client.files.delete.assert_called_once_with(name=mock_audio_file.name)

        # Verify generate_content call
        mock_client.models.generate_content.assert_called_once()
        args, kwargs = mock_client.models.generate_content.call_args

        # Check model parameter
        assert kwargs['model'] == GEMINI_2_5_FLASH

        # Check contents (audio file and prompt)
        assert len(kwargs['contents']) == 2
        assert kwargs['contents'][0] == mock_audio_file
        assert isinstance(kwargs['contents'][1], str)  # USER_PROMPT

        # Check config
        config = kwargs['config']
        assert config.response_mime_type == "application/json"
        assert config.response_schema == Stage1PreprocessTranscriptionExecutor.OUTPUT_SCHEMA
        assert config.max_output_tokens == 8192

        # Verify result
        assert result == '{"transcription": "Test transcription"}'

    def test_run_with_processing_audio(self, mock_genai, mock_audio_file):
        """Test handling of processing audio file"""
        # Setup mock to show processing then completed
        processing_file = Mock()
        processing_file.state.name = "PROCESSING"
        processed_file = Mock()
        processed_file.state.name = "PROCESSED"
        processed_file.name = "test_audio_file"

        mock_client = mock_genai.Client.return_value
        mock_client.files.upload.return_value = processing_file
        mock_client.files.get.side_effect = [processing_file, processed_file]

        # Setup mock response
        mock_result = Mock()
        mock_result.text = json.dumps({"transcription": "Test transcription"})
        mock_client.models.generate_content.return_value = mock_result

        with patch('time.sleep') as mock_sleep:
            result = Stage1PreprocessTranscriptionExecutor.run("test.mp3", "fake-api-key")

        # Verify sleep was called while processing
        mock_sleep.assert_called_with(1)
        # Verify get was called twice (once for processing check, once after sleep)
        assert mock_client.files.get.call_count == 2
        assert result == '{"transcription": "Test transcription"}'

    def test_run_without_api_key(self, mock_genai):
        """Test execution without API key"""
        with pytest.raises(ValueError, match="Google Gemini API key was not set!"):
            Stage1PreprocessTranscriptionExecutor.run("test.mp3", None)

    def test_run_with_upload_error(self, mock_genai):
        """Test handling of upload error"""
        mock_client = mock_genai.Client.return_value
        mock_client.files.upload.side_effect = Exception("Upload failed")

        with pytest.raises(Exception, match="Upload failed"):
            Stage1PreprocessTranscriptionExecutor.run("test.mp3", "fake-api-key")

class TestStage1PreprocessDetectionExecutor:
    @pytest.fixture
    def mock_genai(self):
        with patch('processing_pipeline.stage_1_preprocess.genai') as mock:
            # Mock Client and its methods
            mock_client = Mock()
            mock.Client.return_value = mock_client
            yield mock

    def test_run_success(self, mock_genai):
        """Test successful detection execution"""
        # Setup mock client and response
        mock_client = mock_genai.Client.return_value
        mock_result = Mock()
        mock_result.text = json.dumps({"detection": "Test detection"})
        mock_client.models.generate_content.return_value = mock_result

        # Test data
        transcription = "Test transcription"
        metadata = {
            "radio_station": "Test Station",
            "timestamp": "2024-01-01T00:00:00"
        }

        # Run the executor
        result = Stage1PreprocessDetectionExecutor.run("fake-api-key", transcription, metadata)

        # Verify client creation
        mock_genai.Client.assert_called_once_with(api_key="fake-api-key")

        # Verify generate_content call
        mock_client.models.generate_content.assert_called_once()
        args, kwargs = mock_client.models.generate_content.call_args

        # Check model parameter
        assert kwargs['model'] == GEMINI_2_5_PRO

        # Check contents (should have user prompt)
        assert len(kwargs['contents']) == 1
        assert isinstance(kwargs['contents'][0], str)  # User prompt
        assert "Test transcription" in kwargs['contents'][0]
        assert json.dumps(metadata, indent=2) in kwargs['contents'][0]

        # Check config
        config = kwargs['config']
        assert config.response_mime_type == "application/json"
        assert config.response_schema == Stage1PreprocessDetectionExecutor.OUTPUT_SCHEMA
        assert config.max_output_tokens == 8192
        assert config.system_instruction == Stage1PreprocessDetectionExecutor.SYSTEM_INSTRUCTION

        # Verify result
        assert result == '{"detection": "Test detection"}'

    def test_run_without_api_key(self, mock_genai):
        """Test execution without API key"""
        with pytest.raises(ValueError, match="Google Gemini API key was not set!"):
            Stage1PreprocessDetectionExecutor.run(None, "test", {})

    def test_run_with_generation_error(self, mock_genai):
        """Test handling of generation error"""
        mock_client = mock_genai.Client.return_value
        mock_client.models.generate_content.side_effect = Exception("Generation failed")

        with pytest.raises(Exception, match="Generation failed"):
            Stage1PreprocessDetectionExecutor.run("fake-api-key", "test", {})

    def test_constants_loaded(self):
        """Test that all required constants are loaded"""
        assert Stage1PreprocessDetectionExecutor.SYSTEM_INSTRUCTION
        assert Stage1PreprocessDetectionExecutor.DETECTION_PROMPT
        assert Stage1PreprocessDetectionExecutor.OUTPUT_SCHEMA
        assert isinstance(Stage1PreprocessDetectionExecutor.OUTPUT_SCHEMA, dict)

    def test_transcription_constants_loaded(self):
        """Test that all required constants for transcription are loaded"""
        assert Stage1PreprocessTranscriptionExecutor.USER_PROMPT
        assert Stage1PreprocessTranscriptionExecutor.OUTPUT_SCHEMA
        assert isinstance(Stage1PreprocessTranscriptionExecutor.OUTPUT_SCHEMA, dict)
