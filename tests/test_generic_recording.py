from unittest.mock import Mock, call, patch
import pytest
from generic_recording import (
    capture_audio_stream,
    upload_to_r2_and_clean_up,
    get_metadata,
    insert_recorded_audio_file_into_database,
    generic_audio_processing_pipeline,
    get_url_hash,
    station_to_serve,
)
from radiostations.base import RadioStation
from stations import station_by_code, station_by_process_group

class TestGenericRecording:
    @pytest.fixture
    def mock_ffmpeg(self):
        """Setup mock FFmpeg"""
        with patch('generic_recording.FFmpeg') as mock:
            ffmpeg_instance = Mock()
            mock.return_value.option.return_value.input.return_value.output.return_value = ffmpeg_instance
            yield mock, ffmpeg_instance

    @pytest.fixture
    def mock_radio_station(self):
        """Setup mock radio station"""
        station = Mock(spec=RadioStation)
        station.code = "TEST-FM"
        station.name = "Test Radio"
        station.state = "Test State"
        station.url = "https://test.radio/stream"
        station.sink_name = "virtual_speaker_test"
        station.source_name = "virtual_mic_test"
        return station


    @pytest.fixture
    def mock_supabase_client(self):
        """Setup mock Supabase client"""
        with patch('generic_recording.supabase_client') as mock:
            yield mock

    @pytest.fixture
    def mock_s3_client(self):
        """Setup mock S3 client"""
        with patch('generic_recording.s3_client') as mock:
            yield mock

    @pytest.fixture
    def mock_radio_stations(self, mock_radio_station):
        """Setup mock radio stations dictionary"""
        return {
            "TEST-FM": lambda: mock_radio_station
        }

    def test_capture_audio_stream_success(self, mock_ffmpeg, mock_radio_station):
        """Test successful audio capture"""
        mock_ffmpeg_class, mock_ffmpeg_instance = mock_ffmpeg
        mock_radio_station.is_audio_playing.return_value = True

        with patch('os.path.getsize', return_value=1000):
            result = capture_audio_stream(mock_radio_station, 1800, 64000, 1)

        mock_radio_station.is_audio_playing.assert_called_once()
        mock_ffmpeg_instance.execute.assert_called_once()

        assert result["radio_station_name"] == mock_radio_station.name
        assert result["radio_station_code"] == mock_radio_station.code
        assert result["location_state"] == mock_radio_station.state
        assert result["file_size"] == 1000
        assert "recorded_at" in result
        assert "recording_day_of_week" in result

    def test_capture_audio_stream_not_playing(self, mock_ffmpeg, mock_radio_station):
        """Test audio capture when stream is not playing"""
        mock_radio_station.is_audio_playing.return_value = False

        with patch('time.sleep'):
            result = capture_audio_stream(mock_radio_station, 1800, 64000, 1)

        mock_radio_station.is_audio_playing.assert_called_once()
        assert result is None

    def test_capture_audio_stream_ffmpeg_error(self, mock_ffmpeg, mock_radio_station):
        """Test audio capture when FFmpeg fails"""
        mock_ffmpeg_class, mock_ffmpeg_instance = mock_ffmpeg
        mock_radio_station.is_audio_playing.return_value = True
        mock_ffmpeg_instance.execute.side_effect = Exception("FFmpeg error")

        with patch('time.sleep'):
            result = capture_audio_stream(mock_radio_station, 1800, 64000, 1)

        assert result is None

    def test_get_metadata(self, mock_radio_station):
        """Test metadata generation"""
        file_name = "test.mp3"
        start_time = 1704067200  # 2024-01-01 00:00:00

        def mock_strftime(format_string, *args):
            if format_string == "%Y-%m-%dT%H:%M:%S":
                return "2024-01-01T00:00:00"
            elif format_string == "%A":
                return "Monday"
            return ""

        with patch('os.path.getsize', return_value=1000), \
            patch('time.strftime', side_effect=mock_strftime):
            metadata = get_metadata(file_name, mock_radio_station, start_time)

        assert metadata["file_name"] == file_name
        assert metadata["radio_station_name"] == mock_radio_station.name
        assert metadata["radio_station_code"] == mock_radio_station.code
        assert metadata["location_state"] == mock_radio_station.state
        assert metadata["file_size"] == 1000
        assert metadata["recorded_at"] == "2024-01-01T00:00:00"
        assert metadata["recording_day_of_week"] == "Monday"

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
        with patch('generic_recording.R2_BUCKET_NAME', 'test-bucket'):
            mock_s3_client.upload_file.side_effect = Exception("Upload failed")

            # Expect the exception to be raised
            with pytest.raises(Exception, match="Upload failed"):
                upload_to_r2_and_clean_up("https://test.radio/stream", "test.mp3")

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

    def test_generic_audio_processing_pipeline_success(self, mock_radio_station):
        """Test successful pipeline execution"""
        station_code = "KHOT - 105.9 FM"

        with patch('generic_recording.GenericStation', return_value=mock_radio_station), \
            patch('generic_recording.capture_audio_stream') as mock_capture, \
            patch('generic_recording.upload_to_r2_and_clean_up') as mock_upload, \
            patch('generic_recording.insert_recorded_audio_file_into_database') as mock_insert, \
            patch('psutil.virtual_memory') as mock_memory, \
            patch('time.sleep'):

            # Setup mock returns
            mock_radio_station.is_audio_playing.side_effect = [True, False]  # Play once then stop
            mock_memory.return_value.percent = 50  # Normal memory usage
            mock_capture.return_value = {
                "file_name": "test.mp3",
                "radio_station_name": "Test Radio",
                "radio_station_code": station_code,
                "location_state": "Test State",
                "recorded_at": "2024-01-01T00:00:00",
                "recording_day_of_week": "Monday",
                "file_size": 1000
            }
            mock_upload.return_value = "radio_123456/test.mp3"

            # Run pipeline
            generic_audio_processing_pipeline(
                station_code=station_code,
                duration_seconds=1800,
                audio_birate=64000,
                audio_channels=1,
                repeat=False
            )

            # Verify the flow
            mock_capture.assert_called_once()
            mock_upload.assert_called_once()
            mock_insert.assert_called_once()

    def test_generic_audio_processing_pipeline_high_memory(self, mock_radio_station, mock_supabase_client):
        """Test pipeline with high memory usage"""
        station_code = "KHOT - 105.9 FM"

        # Setup mock Supabase response
        mock_response = Mock()
        mock_response.data = [{"id": 1}]  # Simulate Supabase response structure
        mock_supabase_client.insert_audio_file.return_value = {"id": 1}  # Set return value for insert_audio_file

        with patch('generic_recording.GenericStation', return_value=mock_radio_station), \
            patch('generic_recording.capture_audio_stream') as mock_capture, \
            patch('generic_recording.upload_to_r2_and_clean_up') as mock_upload, \
            patch('psutil.virtual_memory') as mock_memory, \
            patch('time.sleep'):

            mock_radio_station.url = "https://test.radio/stream"

            # Setup mock returns
            mock_memory.return_value.percent = 96  # High memory usage
            mock_radio_station.is_audio_playing.return_value = True
            mock_capture.return_value = {
                "file_name": "test.mp3",
                "radio_station_name": "Test Radio",
                "radio_station_code": station_code,
                "location_state": "Test State",
                "recorded_at": "2024-01-01T00:00:00",
                "recording_day_of_week": "Monday",
                "file_size": 1000
            }
            mock_upload.return_value = "radio_123456/test.mp3"

            # Run pipeline
            generic_audio_processing_pipeline(
                station_code=station_code,
                duration_seconds=1800,
                audio_birate=64000,
                audio_channels=1,
                repeat=False
            )

            # Verify both stop and start_browser calls
            assert mock_radio_station.stop.call_count == 2
            assert mock_radio_station.start_browser.call_count == 2

            # Verify the sequence of calls
            mock_radio_station.stop.assert_has_calls([
                call(unload_modules=False),  # First call during browser restart
                call()  # Second call during cleanup
            ])
            mock_radio_station.start_browser.assert_has_calls([
                call(),  # Initial setup
                call()   # After browser restart
            ])

            # Verify Supabase interaction
            mock_supabase_client.insert_audio_file.assert_called_once_with(
                radio_station_name="Test Radio",
                radio_station_code=station_code,
                location_state="Test State",
                recorded_at="2024-01-01T00:00:00",
                recording_day_of_week="Monday",
                file_path="radio_123456/test.mp3",
                file_size=1000
            )

    def test_generic_audio_processing_pipeline_playback_stopped(self, mock_radio_station, mock_supabase_client):
        """Test pipeline when playback stops"""
        station_code = "KHOT - 105.9 FM"

        with patch('generic_recording.GenericStation', return_value=mock_radio_station), \
            patch('generic_recording.capture_audio_stream') as mock_capture, \
            patch('generic_recording.upload_to_r2_and_clean_up') as mock_upload, \
            patch('psutil.virtual_memory') as mock_memory, \
            patch('time.sleep'):

            mock_radio_station.url = "https://test.radio/stream"

            # Setup mock returns
            mock_memory.return_value.percent = 50
            mock_radio_station.is_audio_playing.return_value = False
            mock_capture.return_value = {
                "file_name": "test.mp3",
                "radio_station_name": "Test Radio",
                "radio_station_code": station_code,
                "location_state": "Test State",
                "recorded_at": "2024-01-01T00:00:00",
                "recording_day_of_week": "Monday",
                "file_size": 1000
            }
            mock_upload.return_value = "radio_123456/test.mp3"

            # Run pipeline
            generic_audio_processing_pipeline(
                station_code=station_code,
                duration_seconds=1800,
                audio_birate=64000,
                audio_channels=1,
                repeat=False
            )

            # Verify both stop and start_browser calls
            assert mock_radio_station.stop.call_count == 2
            assert mock_radio_station.start_browser.call_count == 2

            # Verify the sequence of calls
            mock_radio_station.stop.assert_has_calls([
                call(unload_modules=False),  # First call during browser restart
                call()  # Second call during cleanup
            ])
            mock_radio_station.start_browser.assert_has_calls([
                call(),  # Initial setup
                call()   # After browser restart
            ])

    def test_generic_audio_processing_pipeline_cleanup(self, mock_radio_station, mock_supabase_client):
        """Test pipeline cleanup"""
        station_code = "KHOT - 105.9 FM"

        with patch('generic_recording.GenericStation', return_value=mock_radio_station), \
            patch('generic_recording.capture_audio_stream') as mock_capture, \
            patch('generic_recording.upload_to_r2_and_clean_up') as mock_upload, \
            patch('psutil.virtual_memory') as mock_memory, \
            patch('time.sleep'):

            mock_radio_station.url = "https://test.radio/stream"

            # Setup mock returns
            mock_memory.return_value.percent = 50
            mock_radio_station.is_audio_playing.return_value = True
            mock_capture.return_value = {
                "file_name": "test.mp3",
                "radio_station_name": "Test Radio",
                "radio_station_code": station_code,
                "location_state": "Test State",
                "recorded_at": "2024-01-01T00:00:00",
                "recording_day_of_week": "Monday",
                "file_size": 1000
            }
            mock_upload.return_value = "radio_123456/test.mp3"

            # Run pipeline
            generic_audio_processing_pipeline(
                station_code=station_code,
                duration_seconds=1800,
                audio_birate=64000,
                audio_channels=1,
                repeat=False
            )

            # Verify cleanup
            mock_radio_station.stop.assert_called_once()

    def test_generic_audio_processing_pipeline_invalid_station(self):
        """Test pipeline with invalid station code"""
        with pytest.raises(ValueError, match="Invalid station code: INVALID-FM"):
            generic_audio_processing_pipeline(
                station_code="INVALID-FM",
                duration_seconds=1800,
                audio_birate=64000,
                audio_channels=1,
                repeat=False
            )

    def test_station_to_serve_dispatches_on_process_group(self):
        assert station_to_serve("radio_khot").code == "KHOT - 105.9 FM"

    def test_station_to_serve_rejects_an_unknown_process_group(self):
        with pytest.raises(ValueError, match="Invalid process group: invalid_group"):
            station_to_serve("invalid_group")

    def test_station_to_serve_rejects_a_disabled_station(self):
        disabled = station_by_process_group("radio_khot").model_copy(update={"enabled": False})
        with patch("generic_recording.station_by_process_group", return_value=disabled):
            with pytest.raises(ValueError, match="Station is disabled: KHOT - 105.9 FM"):
                station_to_serve("radio_khot")

    def test_generic_audio_processing_pipeline_rejects_a_disabled_station(self):
        disabled = station_by_code("KHOT - 105.9 FM").model_copy(update={"enabled": False})
        with patch("generic_recording.station_by_code", return_value=disabled):
            with pytest.raises(ValueError, match="Station is disabled: KHOT - 105.9 FM"):
                generic_audio_processing_pipeline(
                    station_code="KHOT - 105.9 FM",
                    duration_seconds=1800,
                    audio_birate=64000,
                    audio_channels=1,
                    repeat=False
                )
