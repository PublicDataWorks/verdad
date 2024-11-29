import json
import os
import pytest
from unittest.mock import Mock, patch
from pydub import AudioSegment
from processing_pipeline.timestamped_transcription_generator import TimestampedTranscriptionGenerator

class TestTimestampedTranscriptionGenerator:
    @pytest.fixture
    def sample_audio_file(self, test_data_dir):
        """Creates a 30-second silent audio file for testing."""
        audio = AudioSegment.silent(duration=30000)  # 30 seconds
        audio_path = os.path.join(test_data_dir, "test_audio.mp3")
        audio.export(audio_path, format="mp3")
        yield audio_path
        if os.path.exists(audio_path):
            os.remove(audio_path)

    @pytest.fixture
    def mock_gemini_response(self):
        """Returns a mock response from the Gemini API."""
        return {
            "segments": [
                {"segment_number": 1, "transcript": "This is the first segment."},
                {"segment_number": 2, "transcript": "This is the second segment."},
                {"segment_number": 3, "transcript": "This is the third segment."}
            ]
        }

    def test_build_timestamped_transcription(self):
        segment_transcriptions = [
            "This is segment one.",
            "This is segment two.",
            "This is segment three."
        ]
        segment_length = 10  # 10 seconds per segment

        expected_output = (
            "[00:00] This is segment one.\n"
            "[00:10] This is segment two.\n"
            "[00:20] This is segment three.\n"
        )

        result = TimestampedTranscriptionGenerator.build_timestamped_transcription(
            segment_transcriptions, segment_length
        )

        assert result == expected_output

    def test_split_file_into_segments(self, sample_audio_file):
        segment_length_ms = 10000  # 10 seconds
        segments = TimestampedTranscriptionGenerator.split_file_into_segments(
            sample_audio_file, segment_length_ms
        )

        # Should create 3 segments for a 30-second file
        assert len(segments) == 3

        # Check if all segment files exist
        for segment in segments:
            assert os.path.exists(segment)

        # Check if segments are approximately the expected length
        for segment in segments:
            audio = AudioSegment.from_mp3(segment)
            assert abs(len(audio) - segment_length_ms) == 0

    def test_split_file_into_two_parts(self, sample_audio_file):
        segment_length = 10  # 10 seconds
        part1, part2 = TimestampedTranscriptionGenerator.split_file_into_two_parts(
            sample_audio_file, segment_length
        )

        # Check if both parts exist
        assert os.path.exists(part1)
        assert os.path.exists(part2)

        # Check if lengths of each part is accurate
        audio1 = AudioSegment.from_mp3(part1)
        audio2 = AudioSegment.from_mp3(part2)
        assert len(audio1) == 10000 # The first part must be rounded down to the nearest multiple of 10 seconds
        assert len(audio2) == 20000 # The remaining part of the audio

    @patch('google.generativeai.GenerativeModel')
    def test_transcribe_segments(self, mock_generative_model, mock_gemini_response, sample_audio_file):
        # Create mock segments
        segment_length_ms = 10000
        segments = TimestampedTranscriptionGenerator.split_file_into_segments(
            sample_audio_file, segment_length_ms
        )

        # Setup mock
        mock_model = Mock()
        mock_model.generate_content.return_value.text = json.dumps(mock_gemini_response)
        mock_generative_model.return_value = mock_model

        # Run transcription
        result = TimestampedTranscriptionGenerator.transcribe_segments(
            segments, "fake-api-key"
        )

        # Verify results
        assert len(result) == 3
        assert result[0]["segment_number"] == 1
        assert result[0]["transcript"] == "This is the first segment."
        assert result[1]["segment_number"] == 2
        assert result[1]["transcript"] == "This is the second segment."
        assert result[2]["segment_number"] == 3
        assert result[2]["transcript"] == "This is the third segment."

    @patch.object(TimestampedTranscriptionGenerator, 'transcribe_segments')
    def test_run(self, mock_transcribe_segments, sample_audio_file):
        mock_transcribe_segments.return_value = [
            {"segment_number": 1, "transcript": "First segment content."},
            {"segment_number": 2, "transcript": "Second segment content."}
        ]

        result = TimestampedTranscriptionGenerator.run(
            sample_audio_file, "fake-api-key", 10
        )

        # Verify the format of the result
        assert "[00:00] First segment content." in result
        assert "[00:10] Second segment content." in result

    def test_run_with_invalid_api_key(self, sample_audio_file):
        with pytest.raises(ValueError, match="Google Gemini API key was not set!"):
            TimestampedTranscriptionGenerator.run(sample_audio_file, None, 10)

    def test_run_with_invalid_file(self):
        with pytest.raises(FileNotFoundError) as exc_info:
            TimestampedTranscriptionGenerator.run("non_existed_file.mp3", "fake-api-key", 10)
        assert str(exc_info.value) == "[Errno 2] No such file or directory: 'non_existed_file.mp3'"

    def test_transcribe_segments_with_empty_segments(self):
        with pytest.raises(ValueError, match="No audio segments provided!"):
            TimestampedTranscriptionGenerator.transcribe_segments([], "fake-api-key")
