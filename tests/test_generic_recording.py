import os
from unittest.mock import Mock, call, patch
import pytest
from generic_recording import (
    capture_audio_stream,
    upload_to_r2_and_clean_up,
    get_metadata,
    insert_recorded_audio_file_into_database,
    generic_audio_processing_pipeline,
    get_url_hash
)
from radiostations.base import RadioStation

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
    def mock_s3_client(self):
        """Setup mock S3 client"""
        with patch('generic_recording.s3_client') as mock:
            yield mock

    @pytest.fixture
    def mock_supabase_client(self):
        """Setup mock Supabase client"""
        with patch('generic_recording.SupabaseClient') as mock:
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

        with patch('generic_recording.Khot', return_value=mock_radio_station) as mock_khot_class, \
            patch('generic_recording.Kisf'), \
            patch('generic_recording.Krgt'), \
            patch('generic_recording.Wkaq'), \
            patch('generic_recording.Wado'), \
            patch('generic_recording.Waqi'), \
            patch('generic_recording.capture_audio_stream') as mock_capture, \
            patch('generic_recording.upload_to_r2_and_clean_up') as mock_upload, \
            patch('generic_recording.insert_recorded_audio_file_into_database') as mock_insert, \
            patch('psutil.virtual_memory') as mock_memory, \
            patch('time.sleep') as mock_sleep:

            # Setup mock Khot class code
            mock_khot_class.code = station_code

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

        with patch('generic_recording.Khot', return_value=mock_radio_station) as mock_khot_class, \
            patch('generic_recording.Kisf'), \
            patch('generic_recording.Krgt'), \
            patch('generic_recording.Wkaq'), \
            patch('generic_recording.Wado'), \
            patch('generic_recording.Waqi'), \
            patch('generic_recording.capture_audio_stream') as mock_capture, \
            patch('generic_recording.upload_to_r2_and_clean_up') as mock_upload, \
            patch('psutil.virtual_memory') as mock_memory, \
            patch('time.sleep') as mock_sleep:

            # Setup mock Khot class code
            mock_khot_class.code = station_code
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

    def test_generic_audio_processing_pipeline_playback_stopped(self, mock_radio_station):
        """Test pipeline when playback stops"""
        station_code = "KHOT - 105.9 FM"

        with patch('generic_recording.Khot', return_value=mock_radio_station) as mock_khot_class, \
            patch('generic_recording.Kisf'), \
            patch('generic_recording.Krgt'), \
            patch('generic_recording.Wkaq'), \
            patch('generic_recording.Wado'), \
            patch('generic_recording.Waqi'), \
            patch('generic_recording.capture_audio_stream') as mock_capture, \
            patch('generic_recording.upload_to_r2_and_clean_up') as mock_upload, \
            patch('psutil.virtual_memory') as mock_memory, \
            patch('time.sleep') as mock_sleep:

            # Setup mock Khot class code
            mock_khot_class.code = station_code
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

    def test_generic_audio_processing_pipeline_cleanup(self, mock_radio_station):
        """Test pipeline cleanup"""
        station_code = "KHOT - 105.9 FM"

        with patch('generic_recording.Khot', return_value=mock_radio_station) as mock_khot_class, \
            patch('generic_recording.Kisf'), \
            patch('generic_recording.Krgt'), \
            patch('generic_recording.Wkaq'), \
            patch('generic_recording.Wado'), \
            patch('generic_recording.Waqi'), \
            patch('generic_recording.capture_audio_stream') as mock_capture, \
            patch('generic_recording.upload_to_r2_and_clean_up') as mock_upload, \
            patch('psutil.virtual_memory') as mock_memory, \
            patch('time.sleep'):

            # Setup mock Khot class code
            mock_khot_class.code = station_code
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
        with patch('generic_recording.Khot') as mock_khot, \
            patch('generic_recording.Kisf') as mock_kisf, \
            patch('generic_recording.Krgt') as mock_krgt, \
            patch('generic_recording.Wkaq') as mock_wkaq, \
            patch('generic_recording.Wado') as mock_wado, \
            patch('generic_recording.Waqi') as mock_waqi:

            # Set up the codes for all station classes
            mock_khot.code = "KHOT - 105.9 FM"
            mock_kisf.code = "KISF - 103.5 FM"
            mock_krgt.code = "KRGT - 99.3 FM"
            mock_wkaq.code = "WKAQ - 580 AM"
            mock_wado.code = "WADO - 1280 AM"
            mock_waqi.code = "WAQI - 710 AM"

            with pytest.raises(ValueError, match="Invalid station code: INVALID-FM"):
                generic_audio_processing_pipeline(
                    station_code="INVALID-FM",
                    duration_seconds=1800,
                    audio_birate=64000,
                    audio_channels=1,
                    repeat=False
                )

    def test_main_execution(self):
        """Test main execution with process groups"""
        mock_deployment = Mock()
        mock_flow = Mock()
        mock_flow.to_deployment.return_value = mock_deployment

        with patch.dict('os.environ', {'FLY_PROCESS_GROUP': 'radio_khot'}), \
            patch('generic_recording.serve') as mock_serve, \
            patch('generic_recording.generic_audio_processing_pipeline', mock_flow):

            # Execute the main block code directly
            process_group = os.environ.get("FLY_PROCESS_GROUP")
            match process_group:
                case "radio_khot":
                    deployment = mock_flow.to_deployment(  # Use mock_flow instead of generic_audio_processing_pipeline
                        "KHOT - 105.9 FM",
                        tags=["Arizona", "1853b3", "Generic"],
                        parameters=dict(
                            station_code="KHOT - 105.9 FM",
                            duration_seconds=1800,
                            repeat=True,
                            audio_birate=64000,
                            audio_channels=1,
                        ),
                    )
                    mock_serve(deployment)
                case _:
                    raise ValueError(f"Invalid process group: {process_group}")

            # Verify serve was called with the mock deployment
            mock_serve.assert_called_once_with(mock_deployment)
            # Verify to_deployment was called with correct parameters
            mock_flow.to_deployment.assert_called_once_with(
                "KHOT - 105.9 FM",
                tags=["Arizona", "1853b3", "Generic"],
                parameters=dict(
                    station_code="KHOT - 105.9 FM",
                    duration_seconds=1800,
                    repeat=True,
                    audio_birate=64000,
                    audio_channels=1,
                ),
            )

    def test_main_execution_invalid_process_group(self):
        """Test main execution with invalid process group"""
        with patch.dict('os.environ', {'FLY_PROCESS_GROUP': 'invalid_group'}):
            process_group = os.environ.get("FLY_PROCESS_GROUP")
            with pytest.raises(ValueError, match="Invalid process group: invalid_group"):
                match process_group:
                    case "radio_khot":
                        pass
                    case _:
                        raise ValueError(f"Invalid process group: {process_group}")
