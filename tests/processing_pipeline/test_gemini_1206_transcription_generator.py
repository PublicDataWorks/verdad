from unittest.mock import Mock, call, patch
import pytest
from google.generativeai.types import HarmCategory, HarmBlockThreshold
from processing_pipeline.gemini_1206_transcription_generator import Gemini1206TranscriptionGenerator


class TestGemini1206TranscriptionGenerator:

    @pytest.fixture
    def mock_genai(self):
        """Setup mock Google Generative AI"""
        with patch("processing_pipeline.gemini_1206_transcription_generator.genai") as mock:
            # Mock GenerationConfig
            mock_config = Mock()
            mock_config.max_output_tokens = 8192
            mock.GenerationConfig.return_value = mock_config

            # Use actual HarmCategory and HarmBlockThreshold
            mock.types.HarmCategory = HarmCategory
            mock.types.HarmBlockThreshold = HarmBlockThreshold

            yield mock

    @pytest.fixture
    def mock_audio_file(self):
        """Create a mock audio file"""
        mock = Mock()
        mock.state.name = "PROCESSED"
        mock.name = "test_audio_file"
        return mock

    def test_run_success(self, mock_genai, mock_audio_file):
        """Test successful transcription generation"""
        # Setup mock response
        mock_result = Mock()
        mock_result.text = "Test transcription"
        mock_model = Mock()
        mock_model.generate_content.return_value = mock_result
        mock_genai.GenerativeModel.return_value = mock_model
        mock_genai.upload_file.return_value = mock_audio_file
        mock_genai.get_file.return_value = mock_audio_file

        # Run the generator
        result = Gemini1206TranscriptionGenerator.run("test.mp3", "fake-api-key")

        # Verify configurations
        mock_genai.configure.assert_called_once_with(api_key="fake-api-key")
        mock_genai.GenerativeModel.assert_called_once_with(model_name="gemini-exp-1206")

        # Verify generate_content call
        mock_model.generate_content.assert_called_once()
        args, kwargs = mock_model.generate_content.call_args
        assert len(args[0]) == 2  # Should have prompt and audio file
        assert args[0][0] == Gemini1206TranscriptionGenerator.USER_PROMPT
        assert args[0][1] == mock_audio_file

        # Verify generation config
        mock_genai.GenerationConfig.assert_called_once_with(max_output_tokens=8192)

        # Verify safety settings in kwargs
        safety_settings = kwargs["safety_settings"]
        expected_safety_settings = {
            HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
        }
        assert safety_settings == expected_safety_settings

        # Verify result
        assert result == "Test transcription"

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
        mock_result.text = "Test transcription"
        mock_model = Mock()
        mock_model.generate_content.return_value = mock_result
        mock_genai.GenerativeModel.return_value = mock_model

        with patch("time.sleep") as mock_sleep:
            result = Gemini1206TranscriptionGenerator.run("test.mp3", "fake-api-key")

        # Verify sleep was called while processing
        mock_sleep.assert_called_with(1)
        assert result == "Test transcription"

    def test_run_without_api_key(self, mock_genai):
        """Test execution without API key"""
        with pytest.raises(ValueError, match="Google Gemini API key was not set!"):
            Gemini1206TranscriptionGenerator.run("test.mp3", None)

    def test_run_with_upload_error(self, mock_genai):
        """Test handling of upload error"""
        mock_genai.upload_file.side_effect = Exception("Upload failed")

        with pytest.raises(Exception, match="Upload failed"):
            Gemini1206TranscriptionGenerator.run("test.mp3", "fake-api-key")

    def test_file_cleanup(self, mock_genai, mock_audio_file):
        """Test that audio file is cleaned up after processing"""
        # Setup mock response
        mock_result = Mock()
        mock_result.text = "Test transcription"
        mock_model = Mock()
        mock_model.generate_content.return_value = mock_result
        mock_genai.GenerativeModel.return_value = mock_model
        mock_genai.upload_file.return_value = mock_audio_file
        mock_genai.get_file.return_value = mock_audio_file

        Gemini1206TranscriptionGenerator.run("test.mp3", "fake-api-key")

        # Verify file cleanup
        mock_audio_file.delete.assert_called_once()

    def test_run_with_generation_error(self, mock_genai, mock_audio_file):
        """Test handling of content generation error"""
        mock_genai.upload_file.return_value = mock_audio_file
        mock_genai.get_file.return_value = mock_audio_file

        # Setup mock to raise error during generation
        mock_model = Mock()
        mock_model.generate_content.side_effect = Exception("Generation failed")
        mock_genai.GenerativeModel.return_value = mock_model

        with pytest.raises(Exception, match="Generation failed"):
            Gemini1206TranscriptionGenerator.run("test.mp3", "fake-api-key")

        # Verify cleanup was still performed
        mock_audio_file.delete.assert_called_once()

    def test_timeout_configuration(self, mock_genai, mock_audio_file):
        """Test timeout configuration in generate_content"""
        # Setup mock response
        mock_result = Mock()
        mock_result.text = "Test transcription"
        mock_model = Mock()
        mock_model.generate_content.return_value = mock_result
        mock_genai.GenerativeModel.return_value = mock_model
        mock_genai.upload_file.return_value = mock_audio_file
        mock_genai.get_file.return_value = mock_audio_file

        Gemini1206TranscriptionGenerator.run("test.mp3", "fake-api-key")

        # Verify timeout in request_options
        args, kwargs = mock_model.generate_content.call_args
        assert kwargs["request_options"]["timeout"] == 1000

    def test_safety_settings_configuration(self, mock_genai, mock_audio_file):
        """Test safety settings configuration"""
        # Setup mock response
        mock_result = Mock()
        mock_result.text = "Test transcription"
        mock_model = Mock()
        mock_model.generate_content.return_value = mock_result
        mock_genai.GenerativeModel.return_value = mock_model
        mock_genai.upload_file.return_value = mock_audio_file
        mock_genai.get_file.return_value = mock_audio_file

        result = Gemini1206TranscriptionGenerator.run("test.mp3", "fake-api-key")

        # Verify safety settings
        args, kwargs = mock_model.generate_content.call_args
        safety_settings = kwargs["safety_settings"]
        assert len(safety_settings) == 4  # Should have all four harm categories

        expected_safety_settings = {
            HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
        }
        assert safety_settings == expected_safety_settings

    def test_run_with_multiple_processing_attempts(self, mock_genai):
        """Test handling of multiple processing attempts"""
        # Setup mock to show multiple processing attempts before completion
        processing_file = Mock()
        processing_file.state.name = "PROCESSING"
        processed_file = Mock()
        processed_file.state.name = "PROCESSED"
        processed_file.name = "test_audio_file"

        mock_genai.upload_file.return_value = processing_file
        mock_genai.get_file.side_effect = [processing_file, processing_file, processed_file]

        # Setup mock response
        mock_result = Mock()
        mock_result.text = "Test transcription"
        mock_model = Mock()
        mock_model.generate_content.return_value = mock_result
        mock_genai.GenerativeModel.return_value = mock_model

        with patch("time.sleep") as mock_sleep:
            result = Gemini1206TranscriptionGenerator.run("test.mp3", "fake-api-key")

        # Verify multiple sleep calls
        assert mock_sleep.call_count == 3
        mock_sleep.assert_has_calls([call(1), call(1), call(1)])
        assert result == "Test transcription"
