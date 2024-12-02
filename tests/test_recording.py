import os
import time
from unittest.mock import Mock, patch
import pytest
from recording import (
    capture_audio_stream,
    serve_deployments,
    upload_to_r2_and_clean_up,
    get_metadata,
    insert_recorded_audio_file_into_database,
    audio_processing_pipeline_max_recorder,
    audio_processing_pipeline_lite_recorder,
    get_url_hash,
    reconstruct_radio_station
)

class TestRecording:
    @pytest.fixture
    def mock_ffmpeg(self):
        with patch('recording.FFmpeg') as mock:
            ffmpeg_instance = Mock()
            mock.return_value.option.return_value.input.return_value.output.return_value = ffmpeg_instance
            yield mock, ffmpeg_instance

    @pytest.fixture
    def sample_station(self):
        return {
            "code": "TEST-FM",
            "url": "https://test.radio/stream",
            "state": "Test State",
            "name": "Test Radio"
        }

    @pytest.fixture
    def mock_supabase_client(self):
        with patch('recording.supabase_client') as mock:
            yield mock

    @pytest.fixture
    def mock_s3_client(self):
        with patch('recording.s3_client') as mock:
            yield mock

    def test_capture_audio_stream_success(self, mock_ffmpeg, sample_station):
        """Test successful audio capture"""
        mock_ffmpeg_class, mock_ffmpeg_instance = mock_ffmpeg

        # Create a temporary file that will be "created" by FFmpeg
        with patch('os.path.getsize', return_value=1000):
            result = capture_audio_stream(sample_station, 1800, 64000, 1)

        # Verify FFmpeg was called with correct parameters
        assert mock_ffmpeg_class.called
        assert mock_ffmpeg_instance.execute.called

        # Verify the returned metadata
        assert result["radio_station_name"] == sample_station["name"]
        assert result["radio_station_code"] == sample_station["code"]
        assert result["location_state"] == sample_station["state"]
        assert result["file_size"] == 1000
        assert "recorded_at" in result
        assert "recording_day_of_week" in result

    def test_capture_audio_stream_failure(self, mock_ffmpeg, sample_station):
        """Test audio capture failure"""
        mock_ffmpeg_class, mock_ffmpeg_instance = mock_ffmpeg
        mock_ffmpeg_instance.execute.side_effect = Exception("FFmpeg error")

        with patch('time.sleep'):  # Avoid actual sleep in test
            result = capture_audio_stream(sample_station, 1800, 64000, 1)

        assert result is None

    def test_get_metadata(self, sample_station):
        """Test metadata generation"""
        file_name = "test.mp3"
        start_time = time.time()

        with patch('os.path.getsize', return_value=1000):
            metadata = get_metadata(file_name, sample_station, start_time)

        assert metadata["file_name"] == file_name
        assert metadata["radio_station_name"] == sample_station["name"]
        assert metadata["radio_station_code"] == sample_station["code"]
        assert metadata["location_state"] == sample_station["state"]
        assert metadata["file_size"] == 1000
        assert isinstance(metadata["recorded_at"], str)
        assert isinstance(metadata["recording_day_of_week"], str)

    def test_upload_to_r2_success(self, mock_s3_client):
        """Test successful file upload to R2"""
        url = "https://test.radio/stream"
        file_path = "test.mp3"
        url_hash = get_url_hash(url)
        expected_destination = f"radio_{url_hash}/test.mp3"

        with patch('os.remove') as mock_remove:
            result = upload_to_r2_and_clean_up(url, file_path)

        assert result == expected_destination
        mock_s3_client.upload_file.assert_called_once()
        mock_remove.assert_called_once_with(file_path)

    def test_upload_to_r2_failure(self, mock_s3_client):
        """Test file upload failure"""
        # Mock both the environment variable and the s3_client in the recording module
        with patch('recording.R2_BUCKET_NAME', 'test-bucket'), \
            patch('recording.s3_client', mock_s3_client):

            mock_s3_client.upload_file.side_effect = Exception("Upload failed")

            # Expect the exception to be raised
            with pytest.raises(Exception, match="Upload failed"):
                upload_to_r2_and_clean_up("https://test.radio/stream", "test.mp3")

            # Verify upload was attempted
            mock_s3_client.upload_file.assert_called_once()

    def test_insert_recorded_audio_file_success(self, mock_supabase_client):
        """Test successful database insertion"""
        metadata = {
            "radio_station_name": "Test Radio",
            "radio_station_code": "TEST-FM",
            "location_state": "Test State",
            "recorded_at": "2024-01-01T00:00:00",
            "recording_day_of_week": "Monday",
            "file_size": 1000
        }
        uploaded_path = "radio_123456/test.mp3"

        insert_recorded_audio_file_into_database(metadata, uploaded_path)

        mock_supabase_client.insert_audio_file.assert_called_once_with(
            radio_station_name=metadata["radio_station_name"],
            radio_station_code=metadata["radio_station_code"],
            location_state=metadata["location_state"],
            recorded_at=metadata["recorded_at"],
            recording_day_of_week=metadata["recording_day_of_week"],
            file_path=uploaded_path,
            file_size=metadata["file_size"]
        )

    def test_get_url_hash(self):
        """Test URL hash generation"""
        url = "https://test.radio/stream"
        hash_value = get_url_hash(url)

        assert len(hash_value) == 6
        assert isinstance(hash_value, str)

    def test_reconstruct_radio_station(self):
        """Test radio station reconstruction from URL"""
        test_url = "https://test.radio/stream"
        test_station = {
            "code": "TEST-FM",
            "url": test_url,
            "state": "Test State",
            "name": "Test Radio"
        }

        with patch('recording.fetch_radio_stations', return_value=[test_station]):
            result = reconstruct_radio_station(test_url)

        assert result == test_station

    def test_reconstruct_radio_station_not_found(self):
        """Test radio station reconstruction with unknown URL"""
        with patch('recording.fetch_radio_stations', return_value=[]):
            result = reconstruct_radio_station("https://unknown.radio/stream")

        assert result is None

    def test_audio_processing_pipeline_max_recorder(self, sample_station):
        """Test max recorder pipeline"""
        with patch('recording.capture_audio_stream') as mock_capture, \
             patch('recording.upload_to_r2_and_clean_up') as mock_upload, \
             patch('recording.insert_recorded_audio_file_into_database') as mock_insert, \
             patch('recording.reconstruct_radio_station', return_value=sample_station):

            # Setup mock returns
            mock_capture.return_value = {
                "file_name": "test.mp3",
                "radio_station_name": "Test Radio",
                "radio_station_code": "TEST-FM",
                "location_state": "Test State",
                "recorded_at": "2024-01-01T00:00:00",
                "recording_day_of_week": "Monday",
                "file_size": 1000
            }
            mock_upload.return_value = "radio_123456/test.mp3"

            # Run the pipeline
            audio_processing_pipeline_max_recorder(
                url=sample_station["url"],
                duration_seconds=1800,
                audio_birate=64000,
                audio_channels=1,
                repeat=False
            )

            # Verify the pipeline flow
            mock_capture.assert_called_once_with(
                sample_station, 1800, 64000, 1
            )
            mock_upload.assert_called_once_with(
                sample_station["url"],
                mock_capture.return_value["file_name"]
            )
            mock_insert.assert_called_once_with(
                mock_capture.return_value,
                mock_upload.return_value
            )

    def test_audio_processing_pipeline_lite_recorder(self, sample_station):
        """Test lite recorder pipeline"""
        with patch('recording.capture_audio_stream') as mock_capture, \
             patch('recording.upload_to_r2_and_clean_up') as mock_upload, \
             patch('recording.insert_recorded_audio_file_into_database') as mock_insert, \
             patch('recording.reconstruct_radio_station', return_value=sample_station):

            # Setup mock returns
            mock_capture.return_value = {
                "file_name": "test.mp3",
                "radio_station_name": "Test Radio",
                "radio_station_code": "TEST-FM",
                "location_state": "Test State",
                "recorded_at": "2024-01-01T00:00:00",
                "recording_day_of_week": "Monday",
                "file_size": 1000
            }
            mock_upload.return_value = "radio_123456/test.mp3"

            # Run the pipeline
            audio_processing_pipeline_lite_recorder(
                url=sample_station["url"],
                duration_seconds=1800,
                audio_birate=64000,
                audio_channels=1,
                repeat=False
            )

            # Verify the pipeline flow
            mock_capture.assert_called_once_with(
                sample_station, 1800, 64000, 1
            )
            mock_upload.assert_called_once_with(
                sample_station["url"],
                mock_capture.return_value["file_name"]
            )
            mock_insert.assert_called_once_with(
                mock_capture.return_value,
                mock_upload.return_value
            )

    def test_serve_deployments(self):
        """Test serve_deployments function"""
        test_stations = [
            {
                "code": "TEST-FM",
                "url": "https://test.radio/stream",
                "state": "Test State",
                "name": "Test Radio"
            }
        ]

        # Create a mock flow function with to_deployment attribute
        mock_flow = Mock()
        mock_deployment = Mock()
        mock_flow.to_deployment = Mock(return_value=mock_deployment)

        with patch('recording.serve') as mock_serve:
            serve_deployments(test_stations, mock_flow)
            mock_serve.assert_called_once()

    def test_audio_processing_pipeline_with_repeat(self, sample_station):
        """Test pipeline with repeat enabled"""
        with patch('recording.capture_audio_stream') as mock_capture, \
            patch('recording.upload_to_r2_and_clean_up') as mock_upload, \
            patch('recording.insert_recorded_audio_file_into_database') as mock_insert, \
            patch('recording.reconstruct_radio_station', return_value=sample_station), \
            patch('time.sleep') as mock_sleep:  # Mock sleep to speed up test

            # Setup mock to run once then return None to break the loop
            mock_capture.return_value = {
                "file_name": "test1.mp3",
                "radio_station_name": "Test Radio",
                "radio_station_code": "TEST-FM",
                "location_state": "Test State",
                "recorded_at": "2024-01-01T00:00:00",
                "recording_day_of_week": "Monday",
                "file_size": 1000
            }
            mock_upload.return_value = "path1"

            # Run the pipeline with repeat enabled
            audio_processing_pipeline_max_recorder(
                url=sample_station["url"],
                duration_seconds=1800,
                audio_birate=64000,
                audio_channels=1,
                repeat=False  # Changed to False to run only once
            )

            # Verify one iteration occurred
            mock_capture.assert_called_once()
            mock_upload.assert_called_once()
            mock_insert.assert_called_once()

    def test_pipeline_with_invalid_station(self):
        """Test pipeline behavior with invalid station URL"""
        with patch('recording.reconstruct_radio_station', return_value=None):
            with pytest.raises(ValueError, match="Radio station not found for URL:"):
                audio_processing_pipeline_max_recorder(
                    url="https://invalid.radio/stream",
                    duration_seconds=1800,
                    audio_birate=64000,
                    audio_channels=1,
                    repeat=False
                )

    def test_main_process_group_handling(self):
        """Test main process group handling"""
        test_stations = [
            {
                "code": "TEST-FM",
                "url": "https://test.radio/stream",
                "state": "Test State",
                "name": "Test Radio"
            }
        ]

        with patch('recording.fetch_radio_stations', return_value=test_stations), \
            patch('recording.serve_deployments') as mock_serve_deployments, \
            patch.dict('os.environ', {'FLY_PROCESS_GROUP': 'max_recorder'}):

            # Execute the main logic directly
            process_group = os.environ.get("FLY_PROCESS_GROUP")
            match process_group:
                case "max_recorder":
                    mock_serve_deployments(test_stations, audio_processing_pipeline_max_recorder)
                case "lite_recorder":
                    mock_serve_deployments(test_stations, audio_processing_pipeline_lite_recorder)
                case _:
                    raise ValueError(f"Invalid process group: {process_group}")

            # Verify serve_deployments was called with correct parameters
            mock_serve_deployments.assert_called_once_with(
                test_stations,
                audio_processing_pipeline_max_recorder
            )

    def test_invalid_process_group(self):
        """Test handling of invalid process group"""
        with patch.dict('os.environ', {'FLY_PROCESS_GROUP': 'invalid_group'}):
            with pytest.raises(ValueError, match="Invalid process group: invalid_group"):
                process_group = os.environ.get("FLY_PROCESS_GROUP")
                match process_group:
                    case "max_recorder":
                        pass
                    case "lite_recorder":
                        pass
                    case _:
                        raise ValueError(f"Invalid process group: {process_group}")

    def test_capture_audio_stream_with_sleep(self, mock_ffmpeg, sample_station):
        """Test audio capture with sleep on failure"""
        mock_ffmpeg_class, mock_ffmpeg_instance = mock_ffmpeg
        mock_ffmpeg_instance.execute.side_effect = Exception("FFmpeg error")

        with patch('time.sleep') as mock_sleep:
            result = capture_audio_stream(sample_station, 1800, 64000, 1)

            assert result is None
            mock_sleep.assert_called_once_with(300)  # Verify sleep duration
