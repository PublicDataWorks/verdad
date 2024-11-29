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

@pytest.fixture(autouse=True)
def disable_prefect_decorator():
    """Disable Prefect decorator for tests

    This fixture automatically disables the Prefect decorator for all tests
    by setting ENABLE_PREFECT_DECORATOR=false. It restores the original
    value after each test.
    """
    original_value = os.getenv('ENABLE_PREFECT_DECORATOR')
    os.environ['ENABLE_PREFECT_DECORATOR'] = 'false'
    yield
    if original_value is None:
        os.environ.pop('ENABLE_PREFECT_DECORATOR', None)
    else:
        os.environ['ENABLE_PREFECT_DECORATOR'] = original_value
