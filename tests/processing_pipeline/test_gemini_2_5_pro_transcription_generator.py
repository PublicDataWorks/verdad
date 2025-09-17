from unittest.mock import Mock, call, patch
import pytest
from google.genai.types import HarmCategory, HarmBlockThreshold
from processing_pipeline.gemini_2_5_pro_transcription_generator import Gemini25ProTranscriptionGenerator


class TestGemini25ProTranscriptionGenerator:

    @pytest.fixture
    def mock_genai(self):
        """Setup mock Google Generative AI"""
        with patch("processing_pipeline.gemini_2_5_pro_transcription_generator.genai") as mock_genai:
            # Mock Client
            mock_client = Mock()
            mock_genai.Client.return_value = mock_client

            # Mock files operations
            mock_client.files.upload.return_value = Mock()
            mock_client.files.get.return_value = Mock()
            mock_client.files.delete.return_value = None

            # Mock models operations
            mock_client.models.generate_content.return_value = Mock()

            yield mock_genai, mock_client

    @pytest.fixture
    def mock_audio_file(self):
        """Create a mock audio file"""
        mock = Mock()
        mock.state = "PROCESSED"
        mock.name = "test_audio_file"
        return mock

    def test_run_success(self, mock_genai, mock_audio_file):
        """Test successful transcription generation"""
        mock_genai_module, mock_client = mock_genai

        # Setup mock response
        mock_result = Mock()
        mock_result.text = "Test transcription"
        mock_client.files.upload.return_value = mock_audio_file
        mock_client.files.get.return_value = mock_audio_file
        mock_client.models.generate_content.return_value = mock_result

        # Run the generator
        result = Gemini25ProTranscriptionGenerator.run("test.mp3", "fake-api-key")

        # Verify client initialization
        mock_genai_module.Client.assert_called_once_with(api_key="fake-api-key")

        # Verify file operations
        mock_client.files.upload.assert_called_once_with(file="test.mp3", config={"mime_type": "audio/mp3"})
        mock_client.files.delete.assert_called_once_with(name="test_audio_file")

        # Verify generate_content call
        mock_client.models.generate_content.assert_called_once()
        args, kwargs = mock_client.models.generate_content.call_args

        # Check model parameter
        assert kwargs["model"] == "gemini-2.5-pro"

        # Check contents
        assert len(kwargs["contents"]) == 2
        assert kwargs["contents"][0] == Gemini25ProTranscriptionGenerator.USER_PROMPT
        assert kwargs["contents"][1] == mock_audio_file

        # Check config
        config = kwargs["config"]
        assert config.max_output_tokens == 8192
        assert len(config.safety_settings) == 4

        # Verify result
        assert result == "Test transcription"

    def test_run_with_processing_audio(self, mock_genai, mock_audio_file):
        """Test handling of processing audio file"""
        mock_genai_module, mock_client = mock_genai

        # Setup mock to show processing then completed
        processing_file = Mock()
        processing_file.state = "PROCESSING"
        processing_file.name = "test_audio_file"
        processed_file = Mock()
        processed_file.state = "PROCESSED"
        processed_file.name = "test_audio_file"

        mock_client.files.upload.return_value = processing_file
        mock_client.files.get.side_effect = [processing_file, processed_file]

        # Setup mock response
        mock_result = Mock()
        mock_result.text = "Test transcription"
        mock_client.models.generate_content.return_value = mock_result

        with patch("time.sleep") as mock_sleep:
            result = Gemini25ProTranscriptionGenerator.run("test.mp3", "fake-api-key")

        # Verify sleep was called while processing
        mock_sleep.assert_called_with(1)
        assert result == "Test transcription"

    def test_run_without_api_key(self, mock_genai):
        """Test execution without API key"""
        with pytest.raises(ValueError, match="Google Gemini API key was not set!"):
            Gemini25ProTranscriptionGenerator.run("test.mp3", None)

    def test_run_with_upload_error(self, mock_genai):
        """Test handling of upload error"""
        mock_genai_module, mock_client = mock_genai
        mock_client.files.upload.side_effect = Exception("Upload failed")

        with pytest.raises(Exception, match="Upload failed"):
            Gemini25ProTranscriptionGenerator.run("test.mp3", "fake-api-key")

    def test_file_cleanup(self, mock_genai, mock_audio_file):
        """Test that audio file is cleaned up after processing"""
        mock_genai_module, mock_client = mock_genai

        # Setup mock response
        mock_result = Mock()
        mock_result.text = "Test transcription"
        mock_client.files.upload.return_value = mock_audio_file
        mock_client.files.get.return_value = mock_audio_file
        mock_client.models.generate_content.return_value = mock_result

        Gemini25ProTranscriptionGenerator.run("test.mp3", "fake-api-key")

        # Verify file cleanup
        mock_client.files.delete.assert_called_once_with(name="test_audio_file")

    def test_run_with_generation_error(self, mock_genai, mock_audio_file):
        """Test handling of content generation error"""
        mock_genai_module, mock_client = mock_genai
        mock_client.files.upload.return_value = mock_audio_file
        mock_client.files.get.return_value = mock_audio_file
        mock_client.models.generate_content.side_effect = Exception("Generation failed")

        with pytest.raises(Exception, match="Generation failed"):
            Gemini25ProTranscriptionGenerator.run("test.mp3", "fake-api-key")

        # Verify cleanup was still performed
        mock_client.files.delete.assert_called_once_with(name="test_audio_file")

    def test_timeout_configuration(self, mock_genai, mock_audio_file):
        """Test timeout configuration in generate_content"""
        mock_genai_module, mock_client = mock_genai

        # Setup mock response
        mock_result = Mock()
        mock_result.text = "Test transcription"
        mock_client.files.upload.return_value = mock_audio_file
        mock_client.files.get.return_value = mock_audio_file
        mock_client.models.generate_content.return_value = mock_result

        Gemini25ProTranscriptionGenerator.run("test.mp3", "fake-api-key")

        # Verify the config includes thinking_config with budget
        args, kwargs = mock_client.models.generate_content.call_args
        config = kwargs["config"]
        assert config.thinking_config.thinking_budget == 1000

    def test_safety_settings_configuration(self, mock_genai, mock_audio_file):
        """Test safety settings configuration"""
        mock_genai_module, mock_client = mock_genai

        # Setup mock response
        mock_result = Mock()
        mock_result.text = "Test transcription"
        mock_client.files.upload.return_value = mock_audio_file
        mock_client.files.get.return_value = mock_audio_file
        mock_client.models.generate_content.return_value = mock_result

        result = Gemini25ProTranscriptionGenerator.run("test.mp3", "fake-api-key")

        # Verify safety settings
        args, kwargs = mock_client.models.generate_content.call_args
        config = kwargs["config"]
        safety_settings = config.safety_settings
        assert len(safety_settings) == 4  # Should have all four harm categories

        # Verify each safety setting has correct category and threshold
        categories_found = set()
        for setting in safety_settings:
            categories_found.add(setting.category)
            assert setting.threshold == HarmBlockThreshold.BLOCK_NONE

        expected_categories = {
            HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
            HarmCategory.HARM_CATEGORY_HATE_SPEECH,
            HarmCategory.HARM_CATEGORY_HARASSMENT,
            HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
        }
        assert categories_found == expected_categories

    def test_run_with_multiple_processing_attempts(self, mock_genai):
        """Test handling of multiple processing attempts"""
        mock_genai_module, mock_client = mock_genai

        # Setup mock to show multiple processing attempts before completion
        processing_file = Mock()
        processing_file.state = "PROCESSING"
        processing_file.name = "test_audio_file"
        processed_file = Mock()
        processed_file.state = "PROCESSED"
        processed_file.name = "test_audio_file"

        mock_client.files.upload.return_value = processing_file
        mock_client.files.get.side_effect = [processing_file, processing_file, processed_file]

        # Setup mock response
        mock_result = Mock()
        mock_result.text = "Test transcription"
        mock_client.models.generate_content.return_value = mock_result

        with patch("time.sleep") as mock_sleep:
            result = Gemini25ProTranscriptionGenerator.run("test.mp3", "fake-api-key")

        # Verify multiple sleep calls
        assert mock_sleep.call_count == 3
        mock_sleep.assert_has_calls([call(1), call(1), call(1)])
        assert result == "Test transcription"
