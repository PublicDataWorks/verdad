import json
from unittest.mock import Mock, patch
import pytest
from google.generativeai.types import HarmCategory, HarmBlockThreshold
from processing_pipeline.stage_1_preprocess import (
    Stage1PreprocessTranscriptionExecutor,
    Stage1PreprocessDetectionExecutor
)
from processing_pipeline.constants import GEMINI_1_5_FLASH, GEMINI_1_5_PRO

class TestStage1PreprocessTranscriptionExecutor:
    @pytest.fixture
    def mock_genai(self):
        with patch('processing_pipeline.stage_1_preprocess.genai') as mock:
            # Mock GenerationConfig
            mock_config = Mock()
            mock_config.response_mime_type = "application/json"
            mock_config.max_output_tokens = 8192
            mock.GenerationConfig.return_value = mock_config
            yield mock

    @pytest.fixture
    def mock_audio_file(self):
        mock = Mock()
        mock.state.name = "PROCESSED"
        mock.name = "test_audio_file"
        return mock

    def test_run_success(self, mock_genai, mock_audio_file):
        """Test successful transcription execution"""
        # Setup mock response
        mock_result = Mock()
        mock_result.text = json.dumps({"transcription": "Test transcription"})
        mock_model = Mock()
        mock_model.generate_content.return_value = mock_result
        mock_genai.GenerativeModel.return_value = mock_model
        mock_genai.upload_file.return_value = mock_audio_file
        mock_genai.get_file.return_value = mock_audio_file

        # Run the executor
        result = Stage1PreprocessTranscriptionExecutor.run("test.mp3", "fake-api-key")

        # Verify configurations
        mock_genai.configure.assert_called_once_with(api_key="fake-api-key")
        mock_genai.GenerativeModel.assert_called_once_with(model_name=GEMINI_1_5_FLASH)

        # Verify generate_content call
        mock_model.generate_content.assert_called_once()
        args, kwargs = mock_model.generate_content.call_args
        assert len(args[0]) == 2  # Should have audio file and prompt
        assert args[0][0] == mock_audio_file
        assert isinstance(args[0][1], str)  # USER_PROMPT

        # Verify generation config
        mock_genai.GenerationConfig.assert_called_once_with(
            response_mime_type="application/json",
            response_schema=Stage1PreprocessTranscriptionExecutor.OUTPUT_SCHEMA,
            max_output_tokens=8192
        )

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

        mock_genai.upload_file.return_value = processing_file
        mock_genai.get_file.side_effect = [processing_file, processed_file]

        # Setup mock response
        mock_result = Mock()
        mock_result.text = json.dumps({"transcription": "Test transcription"})
        mock_model = Mock()
        mock_model.generate_content.return_value = mock_result
        mock_genai.GenerativeModel.return_value = mock_model

        with patch('time.sleep') as mock_sleep:
            result = Stage1PreprocessTranscriptionExecutor.run("test.mp3", "fake-api-key")

        # Verify sleep was called while processing
        mock_sleep.assert_called_with(1)
        assert result == '{"transcription": "Test transcription"}'

    def test_run_without_api_key(self, mock_genai):
        """Test execution without API key"""
        with pytest.raises(ValueError, match="Google Gemini API key was not set!"):
            Stage1PreprocessTranscriptionExecutor.run("test.mp3", None)

    def test_run_with_upload_error(self, mock_genai):
        """Test handling of upload error"""
        mock_genai.upload_file.side_effect = Exception("Upload failed")

        with pytest.raises(Exception, match="Upload failed"):
            Stage1PreprocessTranscriptionExecutor.run("test.mp3", "fake-api-key")

class TestStage1PreprocessDetectionExecutor:
    @pytest.fixture
    def mock_genai(self):
        with patch('processing_pipeline.stage_1_preprocess.genai') as mock:
            # Mock GenerationConfig
            mock_config = Mock()
            mock_config.response_mime_type = "application/json"
            mock_config.max_output_tokens = 8192
            mock.GenerationConfig.return_value = mock_config
            yield mock

    def test_run_success(self, mock_genai):
        """Test successful detection execution"""
        # Setup mock response
        mock_result = Mock()
        mock_result.text = json.dumps({"detection": "Test detection"})
        mock_model = Mock()
        mock_model.generate_content.return_value = mock_result
        mock_genai.GenerativeModel.return_value = mock_model

        # Test data
        transcription = "Test transcription"
        metadata = {
            "radio_station": "Test Station",
            "timestamp": "2024-01-01T00:00:00"
        }

        # Run the executor
        result = Stage1PreprocessDetectionExecutor.run("fake-api-key", transcription, metadata)

        # Verify configurations
        mock_genai.configure.assert_called_once_with(api_key="fake-api-key")
        mock_genai.GenerativeModel.assert_called_once_with(
            model_name=GEMINI_1_5_PRO,
            system_instruction=Stage1PreprocessDetectionExecutor.SYSTEM_INSTRUCTION
        )

        # Verify generate_content call
        mock_model.generate_content.assert_called_once()
        args, kwargs = mock_model.generate_content.call_args
        assert len(args[0]) == 1  # Should have user prompt
        assert isinstance(args[0][0], str)  # User prompt
        assert "Test transcription" in args[0][0]
        assert json.dumps(metadata, indent=2) in args[0][0]

        # Verify generation config
        mock_genai.GenerationConfig.assert_called_once_with(
            response_mime_type="application/json",
            response_schema=Stage1PreprocessDetectionExecutor.OUTPUT_SCHEMA,
            max_output_tokens=8192
        )

        # Verify result
        assert result == '{"detection": "Test detection"}'

    def test_run_without_api_key(self, mock_genai):
        """Test execution without API key"""
        with pytest.raises(ValueError, match="Google Gemini API key was not set!"):
            Stage1PreprocessDetectionExecutor.run(None, "test", {})

    def test_run_with_generation_error(self, mock_genai):
        """Test handling of generation error"""
        mock_model = Mock()
        mock_model.generate_content.side_effect = Exception("Generation failed")
        mock_genai.GenerativeModel.return_value = mock_model

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
