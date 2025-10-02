from unittest.mock import Mock, patch
import pytest
from google.cloud import bigquery_storage
from big_query_storage import (
    get_access_token,
    read_from_big_query_storage_table,
    request_batch_prediction,
    request_online_prediction,
    get_job_status
)
from processing_pipeline.constants import GeminiModel

class TestBigQueryStorage:

    @pytest.fixture(autouse=True)
    def mock_environment(self):
        """Setup test environment variables"""
        env_vars = {
            "GOOGLE_PROJECT_ID": "test-project",
            "GOOGLE_BIGQUERY_DATASET_ID": "test-dataset",
            "GOOGLE_BIGQUERY_TABLE_ID": "test-table",
            "SENTRY_DSN": "https://test@test.ingest.sentry.io/123456",
        }
        with patch.dict('os.environ', env_vars, clear=True), \
             patch('big_query_storage.PROJECT_ID', 'test-project'), \
             patch('big_query_storage.DATASET_ID', 'test-dataset'), \
             patch('big_query_storage.TABLE_ID', 'test-table'):
            yield env_vars

    @pytest.fixture
    def mock_credentials(self):
        """Setup mock credentials"""
        mock_creds = Mock()
        mock_creds.token = "test-token"
        mock_creds.refresh = Mock()
        return mock_creds

    def test_get_access_token_with_service_account(self, mock_credentials):
        """Test getting access token using service account"""
        with patch('google.oauth2.service_account.Credentials.from_service_account_file',
                  return_value=mock_credentials), \
             patch('google.auth.transport.requests.Request'):

            token = get_access_token()
            assert token == "test-token"
            assert mock_credentials.refresh.call_count == 1

    def test_get_access_token_with_default_credentials(self, mock_credentials):
        """Test getting access token using default credentials"""
        with patch('google.oauth2.service_account.Credentials.from_service_account_file',
                side_effect=FileNotFoundError("credentials.json not found")), \
            patch('google.auth._default._get_explicit_environ_credentials', return_value=(None, None)), \
            patch('google.auth._default._get_gcloud_sdk_credentials', return_value=(None, None)), \
            patch('google.auth._default._get_gae_credentials', return_value=(None, None)), \
            patch('google.auth._default._get_gce_credentials', return_value=(mock_credentials, "test-project")):

            token = get_access_token()

            assert token == "test-token"
            assert mock_credentials.refresh.call_count == 1

    def test_request_batch_prediction(self):
        """Test requesting batch prediction"""
        expected_url = "https://us-central1-aiplatform.googleapis.com/v1/projects/test-project/locations/us-central1/batchPredictionJobs"
        expected_headers = {
            "Authorization": "Bearer test-token",
            "Content-Type": "application/json; charset=utf-8",
        }
        expected_body = {
            "displayName": "batch_prediction",
            "model": f"publishers/google/models/{GeminiModel.GEMINI_1_5_FLASH}",
            "inputConfig": {
                "instancesFormat": "bigquery",
                "bigquerySource": {
                    "inputUri": "bq://test-project.test-dataset.test-table"
                }
            },
            "outputConfig": {
                "predictionsFormat": "bigquery",
                "bigqueryDestination": {
                    "outputUri": "bq://test-project.test-dataset.test-table"
                }
            }
        }
        mock_response = Mock()
        mock_response.json.return_value = {"name": "test-job"}

        with patch('big_query_storage.get_access_token', return_value="test-token"), \
             patch('requests.post', return_value=mock_response) as mock_post:

            request_batch_prediction()

            mock_post.assert_called_once_with(
                expected_url,
                headers=expected_headers,
                json=expected_body
            )

    def test_get_job_status(self):
        """Test getting job status"""
        job_id = "test-job-id"
        expected_url = "https://us-central1-aiplatform.googleapis.com/v1/projects/test-project/locations/us-central1/batchPredictionJobs/test-job-id"
        expected_headers = {
            "Authorization": "Bearer test-token",
            "Content-Type": "application/json",
        }
        mock_response = Mock()
        mock_response.json.return_value = {"state": "RUNNING"}

        with patch('big_query_storage.get_access_token', return_value="test-token"), \
             patch('requests.get', return_value=mock_response) as mock_get:

            get_job_status(job_id)

            mock_get.assert_called_once_with(
                expected_url,
                headers=expected_headers
            )

    def test_request_online_prediction(self):
        """Test requesting online prediction"""
        expected_url = f"https://us-central1-aiplatform.googleapis.com/v1/projects/1024948154020/locations/us-central1/publishers/google/models/{GeminiModel.GEMINI_1_5_FLASH}:streamGenerateContent"
        expected_headers = {
            "Authorization": "Bearer test-token",
            "Content-Type": "application/json; charset=utf-8",
        }
        expected_body = {
            "contents": {
                "role": "user",
                "parts": [
                    {"text": "Good morning, how are you?"},
                ]
            }
        }
        mock_response = Mock()
        mock_response.json.return_value = {"result": "success"}

        with patch('big_query_storage.get_access_token', return_value="test-token"), \
            patch('requests.post', return_value=mock_response) as mock_post:

            request_online_prediction()

            mock_post.assert_called_once_with(
                expected_url,
                headers=expected_headers,
                json=expected_body
            )

    def test_read_from_big_query_storage_table_with_service_account(self, mock_credentials):
        """Test reading from BigQuery storage with service account"""
        mock_client = Mock(spec=bigquery_storage.BigQueryReadClient)
        mock_session = Mock()
        mock_rows = Mock()
        mock_rows.rows.return_value = [{"id": 1, "request": "test", "response": "test", "status": "completed"}]

        with patch('google.oauth2.service_account.Credentials.from_service_account_file',
                  return_value=mock_credentials), \
             patch('google.cloud.bigquery_storage.BigQueryReadClient',
                   return_value=mock_client):

            mock_client.create_read_session.return_value = mock_session
            mock_client.read_rows.return_value = mock_rows
            mock_session.streams = [Mock(name="stream1")]

            read_from_big_query_storage_table()

    def test_read_from_big_query_storage_table_eof(self, mock_credentials):
        """Test reading from BigQuery storage with EOF"""
        mock_client = Mock(spec=bigquery_storage.BigQueryReadClient)
        mock_session = Mock()
        mock_rows = Mock()

        # Create an iterator that raises EOFError
        def iter_with_eof(self):
            raise EOFError()

        # Setup the rows mock
        mock_row_iterator = Mock(spec=iter([]))
        mock_row_iterator.__iter__ = iter_with_eof
        mock_rows.rows.return_value = mock_row_iterator

        with patch('google.oauth2.service_account.Credentials.from_service_account_file',
                side_effect=FileNotFoundError("credentials.json not found")), \
            patch('google.auth._default._get_explicit_environ_credentials', return_value=(None, None)), \
            patch('google.auth._default._get_gcloud_sdk_credentials', return_value=(None, None)), \
            patch('google.auth._default._get_gae_credentials', return_value=(None, None)), \
            patch('google.auth._default._get_gce_credentials', return_value=(mock_credentials, "test-project")), \
            patch('google.cloud.bigquery_storage.BigQueryReadClient',
                return_value=mock_client):

            mock_client.create_read_session.return_value = mock_session
            mock_client.read_rows.return_value = mock_rows
            mock_session.streams = [Mock(name="stream1")]

            read_from_big_query_storage_table()  # Should not raise exception

            # Verify the method calls
            mock_client.create_read_session.assert_called_once()
            mock_client.read_rows.assert_called_once()
            mock_rows.rows.assert_called_once_with(mock_session)

    def test_read_from_big_query_storage_table_no_streams(self, mock_credentials):
        """Test reading from BigQuery storage with no streams"""
        mock_client = Mock(spec=bigquery_storage.BigQueryReadClient)
        mock_session = Mock()
        mock_rows = Mock()
        mock_rows.rows.return_value = iter([])

        with patch('google.oauth2.service_account.Credentials.from_service_account_file',
                return_value=mock_credentials), \
            patch('google.cloud.bigquery_storage.BigQueryReadClient',
                return_value=mock_client), \
            patch('google.auth.default', return_value=(mock_credentials, "test-project")):

            mock_client.create_read_session.return_value = mock_session
            mock_client.read_rows.return_value = mock_rows
            mock_session.streams = [Mock(name="stream1")]

            read_from_big_query_storage_table()

            mock_client.create_read_session.assert_called_once()
            mock_client.read_rows.assert_called_once()
