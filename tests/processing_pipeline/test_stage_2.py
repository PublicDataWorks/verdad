import os
from unittest.mock import Mock, call, patch
import pytest
from processing_pipeline.stage_2.tasks import clamp_to_audio
from processing_pipeline.stage_2 import (
    fetch_a_new_stage_1_llm_response_from_supabase,
    fetch_stage_1_llm_response_from_supabase,
    fetch_snippets_from_supabase,
    download_audio_file_from_s3,
    upload_to_r2_and_clean_up,
    extract_snippet_clip,
    insert_new_snippet_to_snippets_table_in_supabase,
    ensure_correct_timestamps,
    process_llm_response,
    audio_clipping,
    undo_audio_clipping,
    convert_formatted_time_str_to_seconds
)
from pydub import AudioSegment

class TestStage2:
    @pytest.fixture
    def mock_supabase_client(self):
        """Setup mock Supabase client"""
        with patch('processing_pipeline.stage_2.flows.SupabaseClient') as MockSupabaseClient:
            mock_client = Mock()
            # Set up default return values
            mock_client.get_a_new_stage_1_llm_response_and_reserve_it.return_value = None
            MockSupabaseClient.return_value = mock_client
            yield mock_client

    @pytest.fixture
    def mock_s3_client(self):
        """Setup mock S3 client"""
        with patch('boto3.client') as mock:
            s3_client = Mock()
            mock.return_value = s3_client
            yield s3_client

    @pytest.fixture
    def sample_audio_file(self, test_data_dir):
        """Creates a test audio file"""
        audio = AudioSegment.silent(duration=30000)  # 30 seconds
        audio_path = os.path.join(test_data_dir, "test_audio.mp3")
        audio.export(audio_path, format="mp3")
        yield audio_path
        if os.path.exists(audio_path):
            os.remove(audio_path)

    def test_fetch_new_stage_1_llm_response(self, mock_supabase_client):
        """Test fetching new stage 1 LLM response"""
        expected_response = {"id": 1, "status": "New"}
        mock_supabase_client.get_a_new_stage_1_llm_response_and_reserve_it.return_value = expected_response

        result = fetch_a_new_stage_1_llm_response_from_supabase(mock_supabase_client)

        assert result == expected_response
        mock_supabase_client.get_a_new_stage_1_llm_response_and_reserve_it.assert_called_once()

    def test_fetch_stage_1_llm_response_by_id(self, mock_supabase_client):
        """Test fetching stage 1 LLM response by ID"""
        expected_response = {"id": 1, "status": "New"}
        mock_supabase_client.get_stage_1_llm_response_by_id.return_value = expected_response

        result = fetch_stage_1_llm_response_from_supabase(mock_supabase_client, 1)

        assert result == expected_response
        mock_supabase_client.get_stage_1_llm_response_by_id.assert_called_once()

    def test_fetch_snippets(self, mock_supabase_client):
        """Test fetching snippets"""
        expected_response = [{"id": "test-id", "file_path": "test/path"}]
        mock_supabase_client.get_snippets_by_ids.return_value = expected_response

        result = fetch_snippets_from_supabase(mock_supabase_client, ["test-id"])

        assert result == expected_response
        mock_supabase_client.get_snippets_by_ids.assert_called_once()

    def test_download_audio_file(self, mock_s3_client):
        """Test downloading audio file from S3"""
        result = download_audio_file_from_s3(mock_s3_client, "test-bucket", "test/path.mp3")

        assert result == "path.mp3"
        mock_s3_client.download_file.assert_called_once()

    def test_upload_to_r2(self, mock_s3_client, test_data_dir):
        """Test uploading to R2"""
        test_file = os.path.join(test_data_dir, "test.mp3")

        # Create the test file
        with open(test_file, "wb") as f:
            f.write(b"test content")

        try:
            result = upload_to_r2_and_clean_up(
                mock_s3_client,
                os.environ['R2_BUCKET_NAME'],
                "test-folder",
                test_file
            )

            assert result == "test-folder/snippets/test.mp3"
            mock_s3_client.upload_file.assert_called_once_with(
                test_file,
                os.environ['R2_BUCKET_NAME'],
                "test-folder/snippets/test.mp3"
            )
        finally:
            # Clean up
            if os.path.exists(test_file):
                os.remove(test_file)

    def test_extract_snippet_clip(self, sample_audio_file):
        """Test extracting snippet clip"""
        audio = AudioSegment.from_mp3(sample_audio_file)
        output_file = "test_snippet.mp3"
        formatted_recorded_at = "2024-01-01T00:00:00Z"

        try:
            result = extract_snippet_clip(
                audio=audio,
                output_file=output_file,
                formatted_start_time="00:00",
                formatted_end_time="00:10",
                context_before_seconds=5,
                context_after_seconds=5,
                formatted_recorded_at=formatted_recorded_at
            )

            assert len(result) == 4
            assert isinstance(result[0], str)  # duration
            assert isinstance(result[1], str)  # start_time
            assert isinstance(result[2], str)  # end_time
            assert isinstance(result[3], str)  # recorded_at
        finally:
            if os.path.exists(output_file):
                os.remove(output_file)

    def test_insert_new_snippet(self, mock_supabase_client):
        """Test inserting new snippet"""
        insert_new_snippet_to_snippets_table_in_supabase(
            supabase_client=mock_supabase_client,
            snippet_uuid="test-id",
            audio_file_id=1,
            stage_1_llm_response_id=1,
            file_path="test/path.mp3",
            file_size=1000,
            recorded_at="2024-01-01T00:00:00",
            duration="00:01:00",
            start_time="00:00:00",
            end_time="00:01:00"
        )

        mock_supabase_client.insert_snippet.assert_called_once()

    def test_ensure_correct_timestamps(self):
        """Test timestamp validation"""
        audio = AudioSegment.silent(duration=30000)  # 30 seconds
        valid_snippets = [
            {"start_time": "00:00", "end_time": "00:10"},
            {"start_time": "00:10", "end_time": "00:20"}
        ]

        # Should not raise exception
        ensure_correct_timestamps(audio, valid_snippets)

        # Test invalid timestamps
        invalid_snippets = [
            {"start_time": "00:40", "end_time": "00:50"}  # Beyond audio duration
        ]
        with pytest.raises(ValueError):
            ensure_correct_timestamps(audio, invalid_snippets)

    def test_process_llm_response(self, mock_supabase_client, sample_audio_file):
        """Test processing LLM response"""
        snippet_file = "snippet_test-id.mp3"  # Expected snippet file name
        llm_response = {
            "id": 1,
            "audio_file": {
                "id": 1,
                "recorded_at": "2024-01-01T00:00:00Z"
            },
            "detection_result": {
                "flagged_snippets": [
                    {
                        "uuid": "test-id",
                        "start_time": "00:00",
                        "end_time": "00:10"
                    }
                ]
            }
        }

        try:
            with patch('os.path.isfile', return_value=True), \
                patch('pydub.AudioSegment.from_mp3') as mock_audio:

                mock_audio.return_value = AudioSegment.silent(duration=30000)

                process_llm_response(
                    supabase_client=mock_supabase_client,
                    llm_response=llm_response,
                    local_file=sample_audio_file,
                    s3_client=Mock(),
                    r2_bucket_name="test-bucket",
                    context_before_seconds=5,
                    context_after_seconds=5
                )

                mock_supabase_client.set_stage_1_llm_response_status.assert_called_with(1, "Processed")
        finally:
            # Clean up any potentially created snippet files
            if os.path.exists(snippet_file):
                os.remove(snippet_file)

    def test_process_llm_response_with_error(self, mock_supabase_client, mock_s3_client, sample_audio_file):
        """Test processing LLM response with error"""
        llm_response = {
            "id": 1,
            "audio_file": {
                "id": 1,
                "recorded_at": "2024-01-01T00:00:00Z"
            },
            "detection_result": {
                "flagged_snippets": [
                    {
                        "uuid": "test-id",
                        "start_time": "00:00",
                        "end_time": "00:10"
                    }
                ]
            }
        }

        with patch('os.path.isfile', return_value=True), \
            patch('pydub.AudioSegment.from_mp3', side_effect=Exception("Test error")):

            process_llm_response(
                supabase_client=mock_supabase_client,
                llm_response=llm_response,
                local_file=sample_audio_file,
                s3_client=mock_s3_client,
                r2_bucket_name=os.environ['R2_BUCKET_NAME'],
                context_before_seconds=5,
                context_after_seconds=5
            )

            mock_supabase_client.set_stage_1_llm_response_status.assert_called_with(
                1, "Error", "Test error"
            )

    def test_convert_formatted_time_str_to_seconds(self):
        """Test time string conversion"""
        assert convert_formatted_time_str_to_seconds("00:00:30") == 30
        assert convert_formatted_time_str_to_seconds("00:01:00") == 60
        assert convert_formatted_time_str_to_seconds("01:00:00") == 3600
        assert convert_formatted_time_str_to_seconds("30") == 30
        assert convert_formatted_time_str_to_seconds("1:30") == 90

        with pytest.raises(ValueError):
            convert_formatted_time_str_to_seconds("invalid")

    def test_convert_formatted_time_str_to_seconds_edge_cases(self):
        """Test time string conversion edge cases"""
        # Test empty string
        with pytest.raises(ValueError):
            convert_formatted_time_str_to_seconds("")

        # Test invalid format
        with pytest.raises(ValueError):
            convert_formatted_time_str_to_seconds("1:2:3:4")

    @patch('time.sleep')
    def test_audio_clipping_flow(self, mock_sleep, mock_supabase_client, mock_s3_client):
        """Test audio clipping flow"""
        mock_supabase_client.get_a_new_stage_1_llm_response_and_reserve_it.side_effect = [
            {"id": 1, "audio_file": {"file_path": "test/path.mp3"}},
            None  # Second call returns None to end the loop
        ]

        with patch('os.remove'), \
             patch('processing_pipeline.stage_2.flows.process_llm_response') as mock_process:

            audio_clipping(
                context_before_seconds=5,
                context_after_seconds=5,
                repeat=False
            )

            mock_process.assert_called_once()
            mock_sleep.assert_not_called()  # Should not sleep when repeat=False

    @patch('time.sleep')
    def test_audio_clipping_flow_with_repeat(self, mock_sleep, mock_supabase_client, mock_s3_client):
        """Test audio clipping flow with repeat"""
        # Setup mock responses with a mutable counter
        counter = {'value': 0}
        def mock_get_response():
            if counter['value'] == 0:
                counter['value'] += 1
                return {"id": 1, "audio_file": {"file_path": "test/path.mp3"}}
            counter['value'] += 1
            if counter['value'] > 3:  # Exit after 3 calls
                raise Exception("Test complete")
            return None

        mock_supabase_client.get_a_new_stage_1_llm_response_and_reserve_it.side_effect = mock_get_response

        with patch('os.remove'), \
            patch('os.path.isfile', return_value=True), \
            patch('processing_pipeline.stage_2.flows.process_llm_response') as mock_process:

            try:
                audio_clipping(
                    context_before_seconds=5,
                    context_after_seconds=5,
                    repeat=True
                )
            except Exception as e:
                if str(e) != "Test complete":
                    raise e

            # Verify process_llm_response was called once
            mock_process.assert_called_once()

            # Verify sleep was called after processing and when no new responses
            assert mock_sleep.call_count >= 2
            mock_sleep.assert_has_calls([
                call(2),  # Sleep after processing
                call(60)  # Sleep when no new responses
            ], any_order=True)

            # Verify file cleanup
            mock_s3_client.download_file.assert_called_with(
                os.environ['R2_BUCKET_NAME'],
                "test/path.mp3",
                "path.mp3"
            )

    def test_undo_audio_clipping(self, mock_supabase_client, mock_s3_client):
        """Test undoing audio clipping"""
        stage_1_llm_response = {
            "id": 1,
            "detection_result": {
                "flagged_snippets": [
                    {"uuid": "test-id-1"},
                    {"uuid": "test-id-2"}
                ]
            }
        }
        snippets = [
            {"id": "test-id-1", "file_path": "test/path1.mp3"},
            {"id": "test-id-2", "file_path": "test/path2.mp3"}
        ]

        mock_supabase_client.get_stage_1_llm_response_by_id.return_value = stage_1_llm_response
        mock_supabase_client.get_snippets_by_ids.return_value = snippets

        undo_audio_clipping([1])

        # Verify snippet deletion calls
        assert mock_s3_client.delete_object.call_count == 2
        assert mock_supabase_client.delete_snippet.call_count == 2
        mock_supabase_client.reset_stage_1_llm_response_status.assert_called_once_with(1)


class TestClampToAudio:
    """Word-anchored ends can land just past the audio (1800 s on a 1799 s file); clamp instead of failing."""

    def test_end_past_the_audio_is_clamped_with_a_warning(self, capsys):
        assert clamp_to_audio(1790, 1800, 1799) == (1790, 1799)
        assert "clamped to 1790-1799" in capsys.readouterr().out

    def test_negative_start_is_clamped(self):
        assert clamp_to_audio(-3, 10, 30) == (0, 10)

    def test_inside_the_audio_is_unchanged(self, capsys):
        assert clamp_to_audio(0, 30, 30) == (0, 30)
        assert capsys.readouterr().out == ""

    def test_start_after_end_still_raises(self):
        with pytest.raises(ValueError, match="less than or equal"):
            clamp_to_audio(20, 10, 30)

    def test_start_past_the_audio_still_raises(self):
        with pytest.raises(ValueError, match="within the audio duration of 30 seconds"):
            clamp_to_audio(40, 50, 30)

    def test_ensure_correct_timestamps_accepts_an_end_past_the_audio(self):
        audio = AudioSegment.silent(duration=30000)
        ensure_correct_timestamps(audio, [{"start_time": "00:20", "end_time": "00:31"}])

    def test_ensure_correct_timestamps_still_rejects_start_after_end(self):
        audio = AudioSegment.silent(duration=30000)
        with pytest.raises(ValueError):
            ensure_correct_timestamps(audio, [{"start_time": "00:20", "end_time": "00:10"}])

    def test_extract_snippet_clip_clamps_the_end(self, test_data_dir):
        audio = AudioSegment.silent(duration=30000)
        output_file = os.path.join(test_data_dir, "clamped.mp3")

        duration, start, end, recorded_at = extract_snippet_clip(
            audio=audio,
            output_file=output_file,
            formatted_start_time="00:20",
            formatted_end_time="00:45",
            context_before_seconds=5,
            context_after_seconds=5,
            formatted_recorded_at="2024-01-01T00:00:00Z",
        )

        # clip 15-30 s: the snippet starts 5 s in and runs to the end of the audio
        assert (duration, start, end) == ("00:15", "00:05", "00:15")
        assert recorded_at == "2024-01-01T00:00:15+00:00"
        assert os.path.exists(output_file)
