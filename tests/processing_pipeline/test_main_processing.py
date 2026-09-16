import importlib
import sys
from unittest.mock import Mock, patch
import pytest

class TestMainProcessing:
    @pytest.fixture(autouse=True)
    def setup_and_teardown(self):
        """Setup and teardown for each test"""
        # Remove the module before each test
        if 'processing_pipeline.main' in sys.modules:
            del sys.modules['processing_pipeline.main']

        yield

        # Clean up after test
        if 'processing_pipeline.main' in sys.modules:
            del sys.modules['processing_pipeline.main']

    def test_sentry_initialization(self, monkeypatch):
        """Test Sentry initialization with DSN"""
        test_dsn = "test-dsn"
        mock_init = Mock()

        # Setup environment and patches before importing
        monkeypatch.setenv('FLY_PROCESS_GROUP', 'initial_disinformation_detection')
        monkeypatch.setenv('SENTRY_DSN', test_dsn)

        with patch.dict('sys.modules', {'sentry_sdk': Mock(init=mock_init)}):
            importlib.import_module('processing_pipeline.main')  # importing runs sentry_sdk.init

            mock_init.assert_called_once_with(dsn=test_dsn)

    def test_sentry_initialization_no_dsn(self, monkeypatch):
        """Test Sentry initialization when DSN is not set"""
        mock_init = Mock()

        # Setup environment before importing
        monkeypatch.setenv('FLY_PROCESS_GROUP', 'initial_disinformation_detection')
        monkeypatch.delenv('SENTRY_DSN', raising=False)

        with patch.dict('sys.modules', {'sentry_sdk': Mock(init=mock_init)}):
            importlib.import_module('processing_pipeline.main')  # importing runs sentry_sdk.init

            mock_init.assert_called_once_with(dsn=None)

    def test_environment_variable_handling(self, monkeypatch):
        """Test environment variable handling"""
        test_cases = [
            {
                'vars': {
                    'FLY_PROCESS_GROUP': 'initial_disinformation_detection',
                    'SENTRY_DSN': 'test-dsn'
                },
                'expected_dsn': 'test-dsn'
            },
            {
                'vars': {
                    'FLY_PROCESS_GROUP': 'initial_disinformation_detection'
                },
                'expected_dsn': None
            }
        ]

        for case in test_cases:
            # Reset modules for each test case
            if 'processing_pipeline.main' in sys.modules:
                del sys.modules['processing_pipeline.main']

            mock_init = Mock()

            # Setup environment variables
            for key, value in case['vars'].items():
                monkeypatch.setenv(key, value)
            if 'SENTRY_DSN' not in case['vars']:
                monkeypatch.delenv('SENTRY_DSN', raising=False)

            with patch.dict('sys.modules', {'sentry_sdk': Mock(init=mock_init)}):
                importlib.import_module('processing_pipeline.main')  # importing runs sentry_sdk.init

                mock_init.assert_called_once_with(dsn=case['expected_dsn'])
                mock_init.reset_mock()
