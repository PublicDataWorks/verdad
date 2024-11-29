import os
import sys
import pytest

# Add src directory to Python path
project_root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
sys.path.insert(0, project_root)

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
