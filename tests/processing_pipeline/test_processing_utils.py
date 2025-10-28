from unittest.mock import Mock, patch
import pytest
from processing_pipeline.processing_utils import (
    create_new_label_and_assign_to_snippet,
    delete_vector_embedding_of_snippet,
    postprocess_snippet,
)


class TestProcessingUtils:
    @pytest.fixture
    def mock_supabase_client(self):
        """Create a mock Supabase client"""
        mock_client = Mock()
        mock_client.create_new_label.return_value = {"id": "test-label-id"}
        mock_client.assign_label_to_snippet.return_value = None
        mock_client.delete_vector_embedding_of_snippet.return_value = None
        return mock_client

    def test_create_new_label_and_assign_to_snippet(self, mock_supabase_client):
        """Test creating and assigning new label"""
        label = {"english": "Test Label", "spanish": "Etiqueta de Prueba"}
        mock_supabase_client.create_new_label.return_value = {"id": 1}

        create_new_label_and_assign_to_snippet(mock_supabase_client, "test-id", label)

        mock_supabase_client.create_new_label.assert_called_once_with(label["english"], label["spanish"])
        mock_supabase_client.assign_label_to_snippet.assert_called_once()

    def test_delete_vector_embedding_of_snippet(self, mock_supabase_client):
        """Test deleting vector embedding"""
        delete_vector_embedding_of_snippet(mock_supabase_client, "test-id")

        mock_supabase_client.delete_vector_embedding_of_snippet.assert_called_once_with("test-id")

    def test_create_new_label_and_assign_error_handling(self, mock_supabase_client):
        """Test error handling in label creation and assignment"""
        mock_supabase_client.create_new_label.side_effect = Exception("Label creation failed")

        with pytest.raises(Exception):
            create_new_label_and_assign_to_snippet(
                mock_supabase_client, "test-id", {"english": "Test Label", "spanish": "Etiqueta de Prueba"}
            )

    @patch("processing_pipeline.processing_utils.create_new_label_and_assign_to_snippet")
    @patch("processing_pipeline.processing_utils.delete_vector_embedding_of_snippet")
    def test_postprocess_snippet(self, mock_delete_vector, mock_create_label, mock_supabase_client):
        """Test postprocess_snippet function"""
        snippet_id = "test-snippet-id"
        disinformation_categories = [
            {"english": "Category 1", "spanish": "Categoría 1"},
            {"english": "Category 2", "spanish": "Categoría 2"},
        ]

        postprocess_snippet(mock_supabase_client, snippet_id, disinformation_categories)

        # Verify create_new_label_and_assign_to_snippet was called for each category
        assert mock_create_label.call_count == 2
        mock_create_label.assert_any_call(mock_supabase_client, snippet_id, disinformation_categories[0])
        mock_create_label.assert_any_call(mock_supabase_client, snippet_id, disinformation_categories[1])

        # Verify delete_vector_embedding_of_snippet was called once
        mock_delete_vector.assert_called_once_with(mock_supabase_client, snippet_id)

    @patch("processing_pipeline.processing_utils.create_new_label_and_assign_to_snippet")
    @patch("processing_pipeline.processing_utils.delete_vector_embedding_of_snippet")
    def test_postprocess_snippet_empty_categories(self, mock_delete_vector, mock_create_label, mock_supabase_client):
        """Test postprocess_snippet with empty categories"""
        snippet_id = "test-snippet-id"
        disinformation_categories = []

        postprocess_snippet(mock_supabase_client, snippet_id, disinformation_categories)

        # Verify create_new_label_and_assign_to_snippet was not called
        mock_create_label.assert_not_called()

        # Verify delete_vector_embedding_of_snippet was still called
        mock_delete_vector.assert_called_once_with(mock_supabase_client, snippet_id)
