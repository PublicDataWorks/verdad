import os
import sys
import pytest

# Add src directory to Python path
project_root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
sys.path.insert(0, project_root)

# Set up environment variables before any imports
os.environ['GOOGLE_GEMINI_PAID_KEY'] = 'test-key'
os.environ['GOOGLE_GEMINI_KEY'] = 'test-key'
os.environ['SUPABASE_URL'] = 'https://test.supabase.co'
os.environ['SUPABASE_KEY'] = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InRlc3QiLCJyb2xlIjoiYW5vbiIsImlhdCI6MTYxNjE1MzYwMCwiZXhwIjoxOTMxNzI5NjAwfQ.test-signature'
os.environ['R2_ENDPOINT_URL'] = 'https://test.r2.endpoint'
os.environ['R2_ACCESS_KEY_ID'] = 'test-access-key'
os.environ['R2_SECRET_ACCESS_KEY'] = 'test-secret-key'
os.environ['R2_BUCKET_NAME'] = 'test-bucket'
os.environ['SENTRY_DSN'] = 'https://test@test.ingest.sentry.io/123456'
os.environ['ENABLE_PREFECT_DECORATOR'] = 'false'

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
