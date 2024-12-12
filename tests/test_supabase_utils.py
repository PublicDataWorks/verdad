from unittest.mock import Mock, patch
import pytest
from processing_pipeline.supabase_utils import SupabaseClient


class TestSupabaseClient:
    @pytest.fixture
    def mock_supabase(self):
        """Setup mock Supabase client"""
        with patch("processing_pipeline.supabase_utils.create_client") as mock_create:
            mock_client = Mock()
            mock_create.return_value = mock_client
            yield mock_client

    @pytest.fixture
    def supabase_client(self, mock_supabase):
        """Create SupabaseClient instance with mocked Supabase"""
        return SupabaseClient("https://test.supabase.co", "test-key")

    def test_initialization(self, mock_supabase):
        """Test SupabaseClient initialization"""
        client = SupabaseClient("https://test.supabase.co", "test-key")
        assert client.client == mock_supabase

    def test_get_a_new_audio_file_and_reserve_it(self, supabase_client, mock_supabase):
        """Test fetching and reserving a new audio file"""
        expected_response = {"id": 1, "status": "New"}
        mock_supabase.rpc.return_value.execute.return_value.data = expected_response

        response = supabase_client.get_a_new_audio_file_and_reserve_it()

        mock_supabase.rpc.assert_called_once_with("fetch_a_new_audio_file_and_reserve_it")
        assert response == expected_response

    def test_get_a_new_stage_1_llm_response_and_reserve_it(self, supabase_client, mock_supabase):
        """Test fetching and reserving a new stage 1 LLM response"""
        expected_response = {"id": 1, "status": "New"}
        mock_supabase.rpc.return_value.execute.return_value.data = expected_response

        response = supabase_client.get_a_new_stage_1_llm_response_and_reserve_it()

        mock_supabase.rpc.assert_called_once_with("fetch_a_new_stage_1_llm_response_and_reserve_it")
        assert response == expected_response

    def test_get_a_new_snippet_and_reserve_it(self, supabase_client, mock_supabase):
        """Test fetching and reserving a new snippet"""
        expected_response = {"id": 1, "status": "New"}
        mock_supabase.rpc.return_value.execute.return_value.data = expected_response

        response = supabase_client.get_a_new_snippet_and_reserve_it()

        mock_supabase.rpc.assert_called_once_with("fetch_a_new_snippet_and_reserve_it")
        assert response == expected_response

    def test_get_snippet_by_id(self, supabase_client, mock_supabase):
        """Test getting snippet by ID"""
        expected_response = [{"id": "test-id", "status": "New"}]
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = (
            expected_response
        )

        response = supabase_client.get_snippet_by_id("test-id")

        mock_supabase.table.assert_called_once_with("snippets")
        mock_supabase.table.return_value.select.assert_called_once_with("*")
        mock_supabase.table.return_value.select.return_value.eq.assert_called_once_with("id", "test-id")
        assert response == expected_response[0]

    def test_get_snippets_by_ids(self, supabase_client, mock_supabase):
        """Test getting snippets by IDs"""
        expected_response = [{"id": "test-id-1"}, {"id": "test-id-2"}]
        mock_supabase.table.return_value.select.return_value.in_.return_value.execute.return_value.data = (
            expected_response
        )

        response = supabase_client.get_snippets_by_ids(["test-id-1", "test-id-2"])

        mock_supabase.table.assert_called_once_with("snippets")
        mock_supabase.table.return_value.select.assert_called_once_with("*")
        mock_supabase.table.return_value.select.return_value.in_.assert_called_once_with(
            "id", ["test-id-1", "test-id-2"]
        )
        assert response == expected_response

    def test_get_audio_file_by_id(self, supabase_client, mock_supabase):
        """Test getting audio file by ID"""
        expected_response = [{"id": 1, "status": "New"}]
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = (
            expected_response
        )

        response = supabase_client.get_audio_file_by_id(1)

        mock_supabase.table.assert_called_once_with("audio_files")
        mock_supabase.table.return_value.select.assert_called_once_with("*")
        mock_supabase.table.return_value.select.return_value.eq.assert_called_once_with("id", 1)
        assert response == expected_response[0]

    def test_get_stage_1_llm_response_by_id(self, supabase_client, mock_supabase):
        """Test getting stage 1 LLM response by ID"""
        expected_response = [{"id": 1, "status": "New"}]
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = (
            expected_response
        )

        response = supabase_client.get_stage_1_llm_response_by_id(1)

        mock_supabase.table.assert_called_once_with("stage_1_llm_responses")
        mock_supabase.table.return_value.select.assert_called_once_with("*")
        mock_supabase.table.return_value.select.return_value.eq.assert_called_once_with("id", 1)
        assert response == expected_response[0]

    def test_set_audio_file_status(self, supabase_client, mock_supabase):
        """Test setting audio file status"""
        expected_response = [{"id": 1, "status": "Processing"}]
        mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value.data = (
            expected_response
        )

        # Test without error message
        response = supabase_client.set_audio_file_status(1, "Processing")
        mock_supabase.table.assert_called_with("audio_files")
        mock_supabase.table.return_value.update.assert_called_with({"status": "Processing"})
        assert response == expected_response

        # Test with error message
        response = supabase_client.set_audio_file_status(1, "Error", "Test error")
        mock_supabase.table.return_value.update.assert_called_with({"status": "Error", "error_message": "Test error"})

    def test_set_stage_1_llm_response_status(self, supabase_client, mock_supabase):
        """Test setting stage 1 LLM response status"""
        expected_response = [{"id": 1, "status": "Processing"}]
        mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value.data = (
            expected_response
        )

        # Test without error message
        response = supabase_client.set_stage_1_llm_response_status(1, "Processing")
        mock_supabase.table.assert_called_with("stage_1_llm_responses")
        mock_supabase.table.return_value.update.assert_called_with({"status": "Processing"})
        assert response == expected_response

        # Test with error message
        response = supabase_client.set_stage_1_llm_response_status(1, "Error", "Test error")
        mock_supabase.table.return_value.update.assert_called_with({"status": "Error", "error_message": "Test error"})

    def test_set_snippet_status(self, supabase_client, mock_supabase):
        """Test setting snippet status"""
        expected_response = [{"id": "test-id", "status": "Processing"}]
        mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value.data = (
            expected_response
        )

        # Test without error message
        response = supabase_client.set_snippet_status("test-id", "Processing")
        mock_supabase.table.assert_called_with("snippets")
        mock_supabase.table.return_value.update.assert_called_with({"status": "Processing"})
        assert response == expected_response

        # Test with error message
        response = supabase_client.set_snippet_status("test-id", "Error", "Test error")
        mock_supabase.table.return_value.update.assert_called_with({"status": "Error", "error_message": "Test error"})

    def test_insert_audio_file(self, supabase_client, mock_supabase):
        """Test inserting audio file"""
        expected_response = [{"id": 1}]
        mock_supabase.table.return_value.insert.return_value.execute.return_value.data = expected_response

        response = supabase_client.insert_audio_file(
            radio_station_name="Test Station",
            radio_station_code="TEST-FM",
            location_state="Test State",
            recorded_at="2024-01-01T00:00:00",
            recording_day_of_week="Monday",
            file_path="test/path.mp3",
            file_size=1000,
        )

        mock_supabase.table.assert_called_once_with("audio_files")
        mock_supabase.table.return_value.insert.assert_called_once_with(
            {
                "radio_station_name": "Test Station",
                "radio_station_code": "TEST-FM",
                "location_state": "Test State",
                "recorded_at": "2024-01-01T00:00:00",
                "recording_day_of_week": "Monday",
                "file_path": "test/path.mp3",
                "file_size": 1000,
            }
        )
        assert response == expected_response[0]

    def test_insert_stage_1_llm_response(self, supabase_client, mock_supabase):
        """Test inserting stage 1 LLM response"""
        expected_response = [{"id": 1}]
        mock_supabase.table.return_value.insert.return_value.execute.return_value.data = expected_response

        response = supabase_client.insert_stage_1_llm_response(
            audio_file_id=1,
            initial_transcription="Test transcription",
            initial_detection_result={"test": "result"},
            transcriptor="gemini-1206",
            timestamped_transcription={"test": "transcription"},
            detection_result={"test": "result"},
            status="New",
        )

        mock_supabase.table.assert_called_once_with("stage_1_llm_responses")
        mock_supabase.table.return_value.insert.assert_called_once_with(
            {
                "audio_file": 1,
                "initial_transcription": "Test transcription",
                "initial_detection_result": {"test": "result"},
                "transcriptor": "gemini-1206",
                "timestamped_transcription": {"test": "transcription"},
                "detection_result": {"test": "result"},
                "status": "New",
            }
        )
        assert response == expected_response[0]

    def test_insert_snippet(self, supabase_client, mock_supabase):
        """Test inserting snippet"""
        expected_response = [{"id": "test-id"}]
        mock_supabase.table.return_value.insert.return_value.execute.return_value.data = expected_response

        response = supabase_client.insert_snippet(
            uuid="test-id",
            audio_file_id=1,
            stage_1_llm_response_id=1,
            file_path="test/path.mp3",
            file_size=1000,
            recorded_at="2024-01-01T00:00:00",
            duration="00:01:00",
            start_time="00:00:00",
            end_time="00:01:00",
        )

        mock_supabase.table.assert_called_once_with("snippets")
        mock_supabase.table.return_value.insert.assert_called_once()
        assert response == expected_response

    def test_ensure_time_format(self, supabase_client):
        """Test time format ensuring"""
        assert supabase_client.ensure_time_format("30") == "00:00:30"
        assert supabase_client.ensure_time_format("01:30") == "00:01:30"
        assert supabase_client.ensure_time_format("01:01:30") == "01:01:30"

        with pytest.raises(ValueError, match="Invalid time format. Expected format: 'HH:MM:SS'"):
            supabase_client.ensure_time_format("01:01:01:01")

    def test_update_snippet(self, supabase_client, mock_supabase):
        """Test updating snippet"""
        expected_response = [{"id": "test-id"}]
        mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value.data = (
            expected_response
        )

        response = supabase_client.update_snippet(
            id="test-id",
            transcription="Test transcription",
            translation="Test translation",
            title="Test title",
            summary="Test summary",
            explanation="Test explanation",
            disinformation_categories=["category1"],
            keywords_detected=["keyword1"],
            language="en",
            confidence_scores={"score": 0.9},
            emotional_tone="neutral",
            context="Test context",
            political_leaning="neutral",
            status="Processed",
            error_message=None,
        )

        mock_supabase.table.assert_called_once_with("snippets")
        mock_supabase.table.return_value.update.assert_called_once()
        assert response == expected_response

    def test_reset_snippet(self, supabase_client, mock_supabase):
        """Test resetting snippet"""
        expected_response = [{"id": "test-id"}]
        mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value.data = (
            expected_response
        )

        response = supabase_client.reset_snippet("test-id")

        mock_supabase.table.assert_called_once_with("snippets")
        mock_supabase.table.return_value.update.assert_called_once()
        assert response == expected_response

    def test_delete_snippet(self, supabase_client, mock_supabase):
        """Test deleting snippet"""
        expected_response = [{"id": "test-id"}]
        mock_supabase.table.return_value.delete.return_value.eq.return_value.execute.return_value.data = (
            expected_response
        )

        response = supabase_client.delete_snippet("test-id")

        # Verify the method calls
        mock_supabase.table.assert_called_once_with("snippets")
        mock_supabase.table.return_value.delete.assert_called_once()
        mock_supabase.table.return_value.delete.return_value.eq.assert_called_once_with("id", "test-id")
        mock_supabase.table.return_value.delete.return_value.eq.return_value.execute.assert_called_once()

        # Verify the response
        assert response == expected_response

    def test_update_stage_1_llm_response_detection_result(self, supabase_client, mock_supabase):
        """Test updating stage 1 LLM response detection result"""
        expected_response = [{"id": 1}]
        mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value.data = (
            expected_response
        )

        detection_result = {"test": "result"}
        response = supabase_client.update_stage_1_llm_response_detection_result(1, detection_result)

        mock_supabase.table.assert_called_once_with("stage_1_llm_responses")
        mock_supabase.table.return_value.update.assert_called_once_with({"detection_result": detection_result})
        assert response == expected_response

    def test_update_stage_1_llm_response_timestamped_transcription(self, supabase_client, mock_supabase):
        """Test updating stage 1 LLM response timestamped transcription"""
        expected_response = [{"id": 1}]
        mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value.data = (
            expected_response
        )

        timestamped_transcription = {"test": "transcription"}
        response = supabase_client.update_stage_1_llm_response_timestamped_transcription(1, timestamped_transcription)

        mock_supabase.table.assert_called_once_with("stage_1_llm_responses")
        mock_supabase.table.return_value.update.assert_called_once_with(
            {"timestamped_transcription": timestamped_transcription}
        )
        assert response == expected_response

    def test_reset_stage_1_llm_response_status(self, supabase_client, mock_supabase):
        """Test resetting stage 1 LLM response status"""
        expected_response = [{"id": 1}]
        mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value.data = (
            expected_response
        )

        response = supabase_client.reset_stage_1_llm_response_status(1)

        mock_supabase.table.assert_called_once_with("stage_1_llm_responses")
        mock_supabase.table.return_value.update.assert_called_once

    def test_get_snippet_by_id_not_found(self, supabase_client, mock_supabase):
        """Test getting snippet by ID when not found"""
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = []

        response = supabase_client.get_snippet_by_id("test-id")

        mock_supabase.table.assert_called_once_with("snippets")
        mock_supabase.table.return_value.select.assert_called_once_with("*")
        mock_supabase.table.return_value.select.return_value.eq.assert_called_once_with("id", "test-id")
        assert response is None

    def test_get_audio_file_by_id_not_found(self, supabase_client, mock_supabase):
        """Test getting audio file by ID when not found"""
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = []

        response = supabase_client.get_audio_file_by_id(1)

        mock_supabase.table.assert_called_once_with("audio_files")
        mock_supabase.table.return_value.select.assert_called_once_with("*")
        mock_supabase.table.return_value.select.return_value.eq.assert_called_once_with("id", 1)
        assert response is None

    def test_get_stage_1_llm_response_by_id_not_found(self, supabase_client, mock_supabase):
        """Test getting stage 1 LLM response by ID when not found"""
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = []

        response = supabase_client.get_stage_1_llm_response_by_id(1)

        mock_supabase.table.assert_called_once_with("stage_1_llm_responses")
        mock_supabase.table.return_value.select.assert_called_once_with("*")
        mock_supabase.table.return_value.select.return_value.eq.assert_called_once_with("id", 1)
        assert response is None

    def test_get_stage_1_llm_response_by_id_with_custom_select(self, supabase_client, mock_supabase):
        """Test getting stage 1 LLM response by ID with custom select"""
        expected_response = [{"id": 1, "custom_field": "value"}]
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = (
            expected_response
        )

        response = supabase_client.get_stage_1_llm_response_by_id(1, select="id,custom_field")

        mock_supabase.table.assert_called_once_with("stage_1_llm_responses")
        mock_supabase.table.return_value.select.assert_called_once_with("id,custom_field")
        assert response == expected_response[0]

    def test_ensure_time_format_edge_cases(self, supabase_client):
        """Test time format ensuring with edge cases"""
        # Test single digit seconds
        assert supabase_client.ensure_time_format("05") == "00:00:05"

        # Test single digit minutes and seconds
        assert supabase_client.ensure_time_format("01:05") == "00:01:05"

        # Test leading zeros
        assert supabase_client.ensure_time_format("01:02:03") == "01:02:03"

        # Test invalid formats
        with pytest.raises(ValueError):
            supabase_client.ensure_time_format(None)

        with pytest.raises(ValueError):
            supabase_client.ensure_time_format("")

        with pytest.raises(ValueError):
            supabase_client.ensure_time_format("1:2:3:4")

    def test_get_a_new_audio_file_and_reserve_it_not_found(self, supabase_client, mock_supabase):
        """Test fetching new audio file when none available"""
        mock_supabase.rpc.return_value.execute.return_value.data = None

        response = supabase_client.get_a_new_audio_file_and_reserve_it()

        mock_supabase.rpc.assert_called_once_with("fetch_a_new_audio_file_and_reserve_it")
        assert response is None

    def test_get_a_new_stage_1_llm_response_and_reserve_it_not_found(self, supabase_client, mock_supabase):
        """Test fetching new stage 1 LLM response when none available"""
        mock_supabase.rpc.return_value.execute.return_value.data = None

        response = supabase_client.get_a_new_stage_1_llm_response_and_reserve_it()

        mock_supabase.rpc.assert_called_once_with("fetch_a_new_stage_1_llm_response_and_reserve_it")
        assert response is None

    def test_get_a_new_snippet_and_reserve_it_not_found(self, supabase_client, mock_supabase):
        """Test fetching new snippet when none available"""
        mock_supabase.rpc.return_value.execute.return_value.data = None

        response = supabase_client.get_a_new_snippet_and_reserve_it()

        mock_supabase.rpc.assert_called_once_with("fetch_a_new_snippet_and_reserve_it")
        assert response is None

    def test_update_snippet_with_null_fields(self, supabase_client, mock_supabase):
        """Test updating snippet with null fields"""
        expected_response = [{"id": "test-id"}]
        mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value.data = (
            expected_response
        )

        response = supabase_client.update_snippet(
            id="test-id",
            transcription=None,
            translation=None,
            title=None,
            summary=None,
            explanation=None,
            disinformation_categories=None,
            keywords_detected=None,
            language=None,
            confidence_scores=None,
            emotional_tone=None,
            context=None,
            political_leaning=None,
            status="New",
            error_message=None,
        )

        mock_supabase.table.assert_called_once_with("snippets")
        mock_supabase.table.return_value.update.assert_called_once()
        assert response == expected_response

    def test_create_new_label_with_special_characters(self, supabase_client, mock_supabase):
        """Test creating new label with special characters"""
        new_label = [{"id": 1, "text": "Test Label & Special Chars"}]
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = []
        mock_supabase.table.return_value.insert.return_value.execute.return_value.data = new_label

        response = supabase_client.create_new_label(
            "Test Label & Special Chars", "Etiqueta de Prueba & Caracteres Especiales"
        )

        mock_supabase.table.return_value.insert.assert_called_once_with(
            {
                "text": "Test Label & Special Chars",
                "text_spanish": "Etiqueta de Prueba & Caracteres Especiales",
                "is_ai_suggested": True,
            }
        )
        assert response == new_label[0]

    def test_assign_label_to_snippet_duplicate_handling(self, supabase_client, mock_supabase):
        """Test assigning same label to snippet multiple times"""
        existing_assignment = [{"label": 1, "snippet": "test-id"}]
        mock_supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = (
            existing_assignment
        )

        # First assignment
        response1 = supabase_client.assign_label_to_snippet(1, "test-id")
        # Second assignment of same label
        response2 = supabase_client.assign_label_to_snippet(1, "test-id")

        assert response1 == existing_assignment[0]
        assert response2 == existing_assignment[0]
        # Verify insert was not called for duplicate assignment
        mock_supabase.table.return_value.insert.assert_not_called()

    def test_get_snippets_by_ids_empty_list(self, supabase_client, mock_supabase):
        """Test getting snippets with empty ID list"""
        response = supabase_client.get_snippets_by_ids([])

        mock_supabase.table.assert_called_once_with("snippets")
        mock_supabase.table.return_value.select.assert_called_once_with("*")
        mock_supabase.table.return_value.select.return_value.in_.assert_called_once_with("id", [])

    def test_reset_audio_file_status_empty_list(self, supabase_client, mock_supabase):
        """Test resetting audio file status with empty ID list"""
        response = supabase_client.reset_audio_file_status([])

        mock_supabase.table.assert_called_once_with("audio_files")
        mock_supabase.table.return_value.update.assert_called_once_with({"status": "New", "error_message": None})
        mock_supabase.table.return_value.update.return_value.in_.assert_called_once_with("id", [])

    def test_get_a_snippet_that_has_no_embedding(self, supabase_client, mock_supabase):
        """Test fetching a snippet that has no embedding"""
        # Test successful case
        expected_response = {"id": "test-id", "status": "New"}
        mock_supabase.rpc.return_value.execute.return_value.data = expected_response

        response = supabase_client.get_a_snippet_that_has_no_embedding()

        mock_supabase.rpc.assert_called_with("fetch_a_snippet_that_has_no_embedding")
        assert response == expected_response

        # Test case where no snippet is found
        mock_supabase.rpc.return_value.execute.return_value.data = None

        response = supabase_client.get_a_snippet_that_has_no_embedding()

        mock_supabase.rpc.assert_called_with("fetch_a_snippet_that_has_no_embedding")
        assert response is None

    def test_upsert_snippet_embedding(self, supabase_client, mock_supabase):
        """Test upserting snippet embedding"""
        # Test data
        snippet_id = "test-id"
        snippet_document = "Test document content"
        document_token_count = 100
        embedding = [0.1, 0.2, 0.3]
        model_name = "text-embedding-3-large"
        status = "Processed"
        error_message = None

        # Test case 1: Insert new embedding (no existing embedding)
        expected_insert_response = [{"id": 1, "snippet": snippet_id}]
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = []
        mock_supabase.table.return_value.insert.return_value.execute.return_value.data = expected_insert_response

        response = supabase_client.upsert_snippet_embedding(
            snippet_id=snippet_id,
            snippet_document=snippet_document,
            document_token_count=document_token_count,
            embedding=embedding,
            model_name=model_name,
            status=status,
            error_message=error_message,
        )

        # Verify insert was called with correct parameters
        mock_supabase.table.return_value.insert.assert_called_once_with(
            {
                "snippet": snippet_id,
                "snippet_document": snippet_document,
                "document_token_count": document_token_count,
                "embedding": embedding,
                "model_name": model_name,
                "status": status,
                "error_message": error_message,
            }
        )
        assert response == expected_insert_response[0]

        # Test case 2: Update existing embedding
        expected_update_response = [{"id": 1, "snippet": snippet_id}]
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [{"id": 1}]
        mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value.data = (
            expected_update_response
        )

        response = supabase_client.upsert_snippet_embedding(
            snippet_id=snippet_id,
            snippet_document=snippet_document,
            document_token_count=document_token_count,
            embedding=embedding,
            model_name=model_name,
            status=status,
            error_message=error_message,
        )

        # Verify update was called with correct parameters
        mock_supabase.table.return_value.update.assert_called_once_with(
            {
                "snippet_document": snippet_document,
                "document_token_count": document_token_count,
                "embedding": embedding,
                "model_name": model_name,
                "status": status,
                "error_message": error_message,
            }
        )
        mock_supabase.table.return_value.update.return_value.eq.assert_called_once_with("snippet", snippet_id)
        assert response == expected_update_response[0]

    def test_upsert_snippet_embedding_with_error(self, supabase_client, mock_supabase):
        """Test upserting snippet embedding with error status"""
        # Test data
        snippet_id = "test-id"
        snippet_document = None
        document_token_count = None
        embedding = None
        model_name = "text-embedding-3-large"
        status = "Error"
        error_message = "Failed to generate embedding"

        # Mock responses
        expected_response = [{"id": 1, "snippet": snippet_id}]
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = []
        mock_supabase.table.return_value.insert.return_value.execute.return_value.data = expected_response

        response = supabase_client.upsert_snippet_embedding(
            snippet_id=snippet_id,
            snippet_document=snippet_document,
            document_token_count=document_token_count,
            embedding=embedding,
            model_name=model_name,
            status=status,
            error_message=error_message,
        )

        # Verify insert was called with correct parameters
        mock_supabase.table.return_value.insert.assert_called_once_with(
            {
                "snippet": snippet_id,
                "snippet_document": snippet_document,
                "document_token_count": document_token_count,
                "embedding": embedding,
                "model_name": model_name,
                "status": status,
                "error_message": error_message,
            }
        )
        assert response == expected_response[0]

    def test_submit_snippet_review(self, supabase_client, mock_supabase):
        """Test submitting snippet review"""
        expected_response = [{"id": "test-id"}]
        mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value.data = (
            expected_response
        )

        response = supabase_client.submit_snippet_review(
            id="test-id",
            transcription="Test transcription",
            translation="Test translation",
            title="Test title",
            summary="Test summary",
            explanation="Test explanation",
            disinformation_categories=["category1"],
            keywords_detected=["keyword1"],
            language="en",
            confidence_scores={"score": 0.9},
            context="Test context",
            political_leaning="neutral",
            grounding_metadata={"source": "test"},
        )

        mock_supabase.table.assert_called_once_with("snippets")
        mock_supabase.table.return_value.update.assert_called_once_with(
            {
                "transcription": "Test transcription",
                "translation": "Test translation",
                "title": "Test title",
                "summary": "Test summary",
                "explanation": "Test explanation",
                "disinformation_categories": ["category1"],
                "keywords_detected": ["keyword1"],
                "language": "en",
                "confidence_scores": {"score": 0.9},
                "context": "Test context",
                "political_leaning": "neutral",
                "grounding_metadata": {"source": "test"},
                "status": "Processed",
                "error_message": None,
            }
        )
        assert response == expected_response

    def test_delete_stage_1_llm_responses(self, supabase_client, mock_supabase):
        """Test deleting stage 1 LLM responses"""
        expected_response = [{"id": 1}, {"id": 2}]
        mock_supabase.table.return_value.delete.return_value.in_.return_value.execute.return_value.data = (
            expected_response
        )

        audio_file_ids = [1, 2]
        response = supabase_client.delete_stage_1_llm_responses(audio_file_ids)

        mock_supabase.table.assert_called_once_with("stage_1_llm_responses")
        mock_supabase.table.return_value.delete.assert_called_once()
        mock_supabase.table.return_value.delete.return_value.in_.assert_called_once_with("audio_file", audio_file_ids)
        assert response == expected_response

    def test_delete_vector_embedding_of_snippet(self, supabase_client, mock_supabase):
        """Test deleting vector embedding of snippet"""
        expected_response = [{"id": 1, "snippet": "test-id"}]
        mock_supabase.table.return_value.delete.return_value.eq.return_value.execute.return_value.data = (
            expected_response
        )

        response = supabase_client.delete_vector_embedding_of_snippet("test-id")

        mock_supabase.table.assert_called_once_with("snippet_embeddings")
        mock_supabase.table.return_value.delete.assert_called_once()
        mock_supabase.table.return_value.delete.return_value.eq.assert_called_once_with("snippet", "test-id")
        assert response == expected_response

    def test_get_a_ready_for_review_snippet_and_reserve_it(self, supabase_client, mock_supabase):
        """Test getting a ready for review snippet"""
        # Test successful case
        expected_response = {"id": "test-id", "status": "ReadyForReview"}
        mock_supabase.rpc.return_value.execute.return_value.data = expected_response

        response = supabase_client.get_a_ready_for_review_snippet_and_reserve_it()

        mock_supabase.rpc.assert_called_with("fetch_a_ready_for_review_snippet_and_reserve_it")
        assert response == expected_response

        # Test case where no snippet is found
        mock_supabase.rpc.return_value.execute.return_value.data = None

        response = supabase_client.get_a_ready_for_review_snippet_and_reserve_it()

        mock_supabase.rpc.assert_called_with("fetch_a_ready_for_review_snippet_and_reserve_it")
        assert response is None

    def test_create_new_label_existing(self, supabase_client, mock_supabase):
        """Test creating new label when label already exists"""
        existing_label = {"id": 1, "text": "Test Label"}
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
            existing_label
        ]

        response = supabase_client.create_new_label("Test Label", "Etiqueta de Prueba")

        mock_supabase.table.return_value.select.assert_called_once()
        mock_supabase.table.return_value.insert.assert_not_called()
        assert response == existing_label

    def test_update_snippet_previous_analysis(self, supabase_client, mock_supabase):
        """Test updating snippet's previous analysis"""
        test_cases = [
            # Basic case with simple analysis
            {
                "snippet_id": "test-id-1",
                "previous_analysis": {
                    "transcription": "Test transcription",
                    "translation": "Test translation",
                    "status": "Processed",
                },
                "expected_response": [{"id": "test-id-1"}],
            },
            # Case with complex nested analysis
            {
                "snippet_id": "test-id-2",
                "previous_analysis": {
                    "transcription": "Test transcription",
                    "translation": "Test translation",
                    "title": {"english": "Test title", "spanish": "Título de prueba"},
                    "summary": {"english": "Test summary", "spanish": "Resumen de prueba"},
                    "disinformation_categories": [{"english": "Category 1", "spanish": "Categoría 1"}],
                    "confidence_scores": {"overall": 0.9, "categories": [{"name": "accuracy", "score": 0.95}]},
                    "status": "Processed",
                },
                "expected_response": [{"id": "test-id-2"}],
            },
            # Case with null values
            {
                "snippet_id": "test-id-3",
                "previous_analysis": {"transcription": None, "translation": None, "title": None, "status": "New"},
                "expected_response": [{"id": "test-id-3"}],
            },
        ]

        for case in test_cases:
            # Reset mock for each test case
            mock_supabase.reset_mock()
            mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value.data = case[
                "expected_response"
            ]

            # Execute the update
            response = supabase_client.update_snippet_previous_analysis(case["snippet_id"], case["previous_analysis"])

            # Verify the calls and response
            mock_supabase.table.assert_called_once_with("snippets")
            mock_supabase.table.return_value.update.assert_called_once_with(
                {"previous_analysis": case["previous_analysis"]}
            )
            mock_supabase.table.return_value.update.return_value.eq.assert_called_once_with("id", case["snippet_id"])
            assert response == case["expected_response"]
