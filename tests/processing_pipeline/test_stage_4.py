from unittest.mock import Mock, patch, call
import pytest
from processing_pipeline.stage_4 import (
    fetch_a_snippet_that_has_no_embedding,
    upsert_snippet_embedding_to_supabase,
    generate_snippet_document,
    generate_snippet_embedding,
    embedding,
    Stage4Executor
)

class TestStage4:
    @pytest.fixture
    def mock_supabase_client(self):
        """Setup mock Supabase client"""
        with patch('processing_pipeline.stage_4.SupabaseClient') as MockSupabaseClient:
            mock_client = Mock()
            mock_client.get_a_snippet_that_has_no_embedding.return_value = None
            MockSupabaseClient.return_value = mock_client
            yield mock_client

    @pytest.fixture
    def sample_snippet(self):
        """Create a sample snippet for testing"""
        return {
            "id": "test-id",
            "title": {"english": "Test Title"},
            "summary": {"english": "Test Summary"},
            "explanation": {"english": "Test Explanation"},
            "transcription": "Test Transcription",
            "disinformation_categories": [
                {"english": "Category 1"},
                {"english": "Category 2"}
            ]
        }

    @pytest.fixture
    def mock_openai(self):
        """Setup mock OpenAI client"""
        with patch('processing_pipeline.stage_4.OpenAI') as MockOpenAI:
            mock_client = Mock()
            mock_response = Mock()
            mock_response.data = [Mock(embedding=[0.1, 0.2, 0.3])]
            mock_client.embeddings.create.return_value = mock_response
            MockOpenAI.return_value = mock_client
            yield mock_client

    def test_fetch_snippet_without_embedding(self, mock_supabase_client):
        """Test fetching a snippet without embedding"""
        expected_response = {"id": "test-id", "status": "New"}
        mock_supabase_client.get_a_snippet_that_has_no_embedding.return_value = expected_response

        result = fetch_a_snippet_that_has_no_embedding(mock_supabase_client)

        assert result == expected_response
        mock_supabase_client.get_a_snippet_that_has_no_embedding.assert_called_once()

    def test_upsert_snippet_embedding(self, mock_supabase_client):
        """Test upserting snippet embedding"""
        upsert_snippet_embedding_to_supabase(
            supabase_client=mock_supabase_client,
            snippet_id="test-id",
            snippet_document="Test document",
            document_token_count=100,
            embedding=[0.1, 0.2, 0.3],
            model_name="test-model",
            status="Processed",
            error_message=None
        )

        mock_supabase_client.upsert_snippet_embedding.assert_called_once_with(
            snippet_id="test-id",
            snippet_document="Test document",
            document_token_count=100,
            embedding=[0.1, 0.2, 0.3],
            model_name="test-model",
            status="Processed",
            error_message=None
        )

    def test_generate_snippet_document(self, sample_snippet):
        """Test generating snippet document"""
        result = generate_snippet_document(sample_snippet)

        assert "Title: Test Title" in result
        assert "Summary: Test Summary" in result
        assert "Explanation: Test Explanation" in result
        assert "Content: Test Transcription" in result
        assert "Topics: Category 1, Category 2" in result

    def test_generate_snippet_embedding_success(self, mock_supabase_client, mock_openai):
        """Test successful generation of snippet embedding"""
        with patch('processing_pipeline.stage_4.encoding_for_model') as mock_encoding, \
             patch('os.getenv', return_value='test-key'), \
             patch('processing_pipeline.stage_4.Stage4Executor.run',
                   return_value=[0.1, 0.2, 0.3]) as mock_run:
            # Setup token counting mock
            mock_encoding_instance = Mock()
            mock_encoding_instance.encode.return_value = [1, 2, 3]  # 3 tokens
            mock_encoding.return_value = mock_encoding_instance

            generate_snippet_embedding(
                supabase_client=mock_supabase_client,
                snippet_id="test-id",
                snippet_document="Test document"
            )

            # Verify token counting
            mock_encoding.assert_called_once_with("text-embedding-3-large")
            mock_encoding_instance.encode.assert_called_once_with("Test document")

            # Verify Stage4Executor.run was called
            mock_run.assert_called_once_with("Test document", "text-embedding-3-large")

            # Verify upsert call
            mock_supabase_client.upsert_snippet_embedding.assert_called_once_with(
                snippet_id="test-id",
                snippet_document="Test document",
                document_token_count=3,
                embedding=[0.1, 0.2, 0.3],
                model_name="text-embedding-3-large",
                status="Processed",
                error_message=None
            )

    def test_generate_snippet_embedding_token_count_error(self, mock_supabase_client, mock_openai):
        """Test embedding generation with token counting error"""
        with patch('processing_pipeline.stage_4.encoding_for_model',
                  side_effect=Exception("Token count error")), \
             patch('os.getenv', return_value=None):
            generate_snippet_embedding(
                supabase_client=mock_supabase_client,
                snippet_id="test-id",
                snippet_document="Test document"
            )

            # Verify upsert was called with None token count
            mock_supabase_client.upsert_snippet_embedding.assert_called_once_with(
                snippet_id="test-id",
                snippet_document="Test document",
                document_token_count=None,
                embedding=None,
                model_name="text-embedding-3-large",
                status="Error",
                error_message="OpenAI API key was not set!"
            )

    def test_generate_snippet_embedding_embedding_error(self, mock_supabase_client):
        """Test embedding generation with OpenAI error"""
        with patch('processing_pipeline.stage_4.encoding_for_model') as mock_encoding, \
             patch('processing_pipeline.stage_4.Stage4Executor.run', side_effect=Exception("Embedding error")):

            # Setup token counting mock
            mock_encoding_instance = Mock()
            mock_encoding_instance.encode.return_value = [1, 2, 3]
            mock_encoding.return_value = mock_encoding_instance

            generate_snippet_embedding(
                supabase_client=mock_supabase_client,
                snippet_id="test-id",
                snippet_document="Test document"
            )

            # Verify error handling in upsert
            mock_supabase_client.upsert_snippet_embedding.assert_called_once_with(
                snippet_id="test-id",
                snippet_document="Test document",
                document_token_count=3,
                embedding=None,
                model_name="text-embedding-3-large",
                status="Error",
                error_message="Embedding error"
            )

    def test_stage_4_executor(self, mock_openai):
        """Test Stage4Executor"""
        with patch('os.getenv', return_value="test-key"):
            result = Stage4Executor.run("Test text", "test-model")

            assert result == [0.1, 0.2, 0.3]
            mock_openai.embeddings.create.assert_called_once_with(
                model="test-model",
                input="Test text"
            )

    def test_stage_4_executor_no_api_key(self):
        """Test Stage4Executor without API key"""
        with patch('os.getenv', return_value=None):
            with pytest.raises(ValueError, match="OpenAI API key was not set!"):
                Stage4Executor.run("Test text", "test-model")

    @patch('time.sleep')
    def test_embedding_flow(self, mock_sleep, mock_supabase_client, sample_snippet):
        """Test embedding flow"""
        # Setup mock to return one snippet then None
        mock_supabase_client.return_value = mock_supabase_client
        mock_supabase_client.get_a_snippet_that_has_no_embedding.side_effect = [
            sample_snippet,
            None
        ]

        with patch('processing_pipeline.stage_4.generate_snippet_document') as mock_generate_document, \
             patch('processing_pipeline.stage_4.generate_snippet_embedding') as mock_generate_embedding, \
             patch('processing_pipeline.stage_4.SupabaseClient', return_value=mock_supabase_client), \
             patch('os.getenv', return_value='test-key'):

            mock_generate_document.return_value = "Test document"

            mock_sleep.reset_mock()

            embedding(repeat=False)

            # Verify the flow
            mock_generate_document.assert_called_once_with(sample_snippet)
            mock_generate_embedding.assert_called_once_with(
                mock_supabase_client,
                sample_snippet["id"],
                "Test document"
            )
            mock_sleep.assert_not_called()  # Should not sleep when only running once

    @patch('time.sleep')
    def test_embedding_flow_with_repeat(self, mock_sleep, mock_supabase_client, sample_snippet):
        """Test embedding flow with repeat"""
        mock_supabase_client.return_value = mock_supabase_client

        # Setup counter for side effect
        call_count = 0
        def side_effect():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return sample_snippet
            elif call_count == 2:
                return None
            raise Exception("Test complete")

        mock_supabase_client.get_a_snippet_that_has_no_embedding.side_effect = side_effect

        with patch('processing_pipeline.stage_4.generate_snippet_document') as mock_generate_document, \
             patch('processing_pipeline.stage_4.generate_snippet_embedding') as mock_generate_embedding, \
             patch('processing_pipeline.stage_4.SupabaseClient', return_value=mock_supabase_client), \
             patch('os.getenv', return_value='test-key'):

            try:
                embedding(repeat=True)
            except Exception as e:
                if str(e) != "Test complete":
                    raise e

            # Verify sleep calls
            assert mock_sleep.call_count >= 2
            mock_sleep.assert_has_calls([call(2), call(60)])
