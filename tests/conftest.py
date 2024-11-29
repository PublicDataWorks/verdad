import os
import sys
from unittest.mock import patch, Mock
import pytest

# Add src directory to Python path
project_root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
sys.path.insert(0, project_root)

# Set up environment variables before any imports
os.environ['SUPABASE_URL'] = 'https://test.supabase.co'
os.environ['SUPABASE_KEY'] = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InRlc3QiLCJyb2xlIjoiYW5vbiIsImlhdCI6MTYxNjE1MzYwMCwiZXhwIjoxOTMxNzI5NjAwfQ.test-signature'
os.environ['R2_ENDPOINT_URL'] = 'https://test.r2.endpoint'
os.environ['R2_ACCESS_KEY_ID'] = 'test-access-key'
os.environ['R2_SECRET_ACCESS_KEY'] = 'test-secret-key'
os.environ['R2_BUCKET_NAME'] = 'test-bucket'
os.environ['SENTRY_DSN'] = 'https://test@test.ingest.sentry.io/123456'
os.environ['ENABLE_PREFECT_DECORATOR'] = 'false'

# Mock Supabase client before any imports
mock_supabase_instance = Mock()
mock_supabase = Mock(return_value=mock_supabase_instance)
with patch('supabase.create_client', mock_supabase):
    from processing_pipeline.supabase_utils import SupabaseClient

@pytest.fixture(autouse=True)
def mock_env_vars():
    """Mock environment variables"""
    env_vars = {
        'SUPABASE_URL': 'https://test.supabase.co',
        'SUPABASE_KEY': 'test-key',
        'R2_ENDPOINT_URL': 'https://test.r2.endpoint',
        'R2_ACCESS_KEY_ID': 'test-access-key',
        'R2_SECRET_ACCESS_KEY': 'test-secret-key',
        'R2_BUCKET_NAME': 'test-bucket',
        'SENTRY_DSN': 'https://test@test.ingest.sentry.io/123456',
        'ENABLE_PREFECT_DECORATOR': 'false'
    }
    with patch.dict('os.environ', env_vars, clear=True):
        yield env_vars

@pytest.fixture
def mock_supabase_client():
    """Return the mocked Supabase client instance"""
    mock_instance = Mock()

    # Setup mock response for insert_audio_file
    mock_instance.insert_audio_file.return_value = {"id": 1}

    # Setup mock table operations if needed
    mock_table = Mock()
    mock_table.insert.return_value.execute.return_value.data = [{"id": 1}]
    mock_instance.table.return_value = mock_table

    return mock_instance

@pytest.fixture
def test_data_dir():
    """Returns the path to the test data directory."""
    dir_path = os.path.join(os.path.dirname(__file__), "test_data")
    os.makedirs(dir_path, exist_ok=True)
    yield dir_path
    # Cleanup
    for file in os.listdir(dir_path):
        os.remove(os.path.join(dir_path, file))
    os.rmdir(dir_path)
