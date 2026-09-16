import importlib
import sys
from unittest.mock import Mock, patch
import pytest

class TestMainProcessing:
    @pytest.fixture(autouse=True)
    def fresh_module(self):
        """Importing processing_pipeline.main is the behaviour under test, so drop it before and after"""
        sys.modules.pop('processing_pipeline.main', None)
        yield
        sys.modules.pop('processing_pipeline.main', None)

    def test_sentry_initialization(self, monkeypatch):
        test_dsn = "test-dsn"
        mock_init = Mock()
        monkeypatch.setenv('FLY_PROCESS_GROUP', 'initial_disinformation_detection')
        monkeypatch.setenv('SENTRY_DSN', test_dsn)

        with patch.dict('sys.modules', {'sentry_sdk': Mock(init=mock_init)}):
            importlib.import_module('processing_pipeline.main')

            mock_init.assert_called_once_with(dsn=test_dsn)

    def test_sentry_initialization_no_dsn(self, monkeypatch):
        mock_init = Mock()
        monkeypatch.setenv('FLY_PROCESS_GROUP', 'initial_disinformation_detection')
        monkeypatch.delenv('SENTRY_DSN', raising=False)

        with patch.dict('sys.modules', {'sentry_sdk': Mock(init=mock_init)}):
            importlib.import_module('processing_pipeline.main')

            mock_init.assert_called_once_with(dsn=None)

    def test_environment_variable_handling(self, monkeypatch):
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
            sys.modules.pop('processing_pipeline.main', None)
            mock_init = Mock()
            for key, value in case['vars'].items():
                monkeypatch.setenv(key, value)
            if 'SENTRY_DSN' not in case['vars']:
                monkeypatch.delenv('SENTRY_DSN', raising=False)

            with patch.dict('sys.modules', {'sentry_sdk': Mock(init=mock_init)}):
                importlib.import_module('processing_pipeline.main')

                mock_init.assert_called_once_with(dsn=case['expected_dsn'])
                mock_init.reset_mock()
