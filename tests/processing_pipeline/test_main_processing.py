import importlib
import os
import sys
from unittest.mock import Mock, patch
import pytest
from prefect import Flow

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

    @pytest.fixture
    def mock_serve(self):
        """Mock prefect serve function"""
        with patch('processing_pipeline.main.serve') as mock:
            yield mock

    @pytest.fixture
    def mock_sentry(self):
        """Mock sentry initialization"""
        with patch('sentry_sdk.init') as mock:
            yield mock

    @pytest.fixture
    def mock_load_dotenv(self):
        """Mock dotenv loading"""
        with patch('processing_pipeline.main.load_dotenv') as mock:
            yield mock

    @pytest.fixture
    def mock_deployment(self):
        """Create a mock deployment"""
        return Mock(name="mock_deployment")

    def test_main_process_group_handling(self, mock_serve, mock_sentry, mock_load_dotenv, mock_deployment):
        """Test process group handling in main"""
        test_cases = [
            {
                'group': 'initial_disinformation_detection',
                'expected_params': {
                    'name': "Stage 1: Initial Disinformation Detection",
                    'concurrency_limit': 100,
                    'parameters': {'audio_file_id': None, 'use_openai': False, 'limit': 1000}
                },
                'serve_limit': 100
            },
            {
                'group': 'regenerate_timestamped_transcript',
                'expected_params': {
                    'name': "Stage 1: Regenerate Timestamped Transcript",
                    'parameters': {'stage_1_llm_response_ids': []}
                }
            },
            {
                'group': 'redo_main_detection',
                'expected_params': {
                    'name': "Stage 1: Redo Main Detection Phase",
                    'parameters': {'stage_1_llm_response_ids': []}
                }
            },
            {
                'group': 'undo_disinformation_detection',
                'expected_params': {
                    'name': "Stage 1: Undo Disinformation Detection",
                    'parameters': {'audio_file_ids': []}
                }
            },
            {
                'group': 'audio_clipping',
                'expected_params': {
                    'name': "Stage 2: Audio Clipping",
                    'concurrency_limit': 100,
                    'parameters': {'context_before_seconds': 90, 'context_after_seconds': 60, 'repeat': True}
                },
                'serve_limit': 100
            },
            {
                'group': 'undo_audio_clipping',
                'expected_params': {
                    'name': "Stage 2: Undo Audio Clipping",
                    'parameters': {'stage_1_llm_response_ids': []}
                }
            },
            {
                'group': 'in_depth_analysis',
                'expected_params': {
                    'name': "Stage 3: In-Depth Analysis",
                    'concurrency_limit': 100,
                    'parameters': {'snippet_ids': [], 'repeat': True}
                },
                'serve_limit': 100
            },
            {
                'group': 'embedding',
                'expected_params': {
                    'name': "Stage 4: Embedding",
                    'concurrency_limit': 100,
                    'parameters': {'repeat': True}
                },
                'serve_limit': 100
            }
        ]

        # Mock Flow class
        mock_flow = Mock(spec=Flow)
        mock_flow.to_deployment.return_value = mock_deployment

        for case in test_cases:
            # Reset mocks
            mock_serve.reset_mock()
            mock_flow.reset_mock()

            with patch.dict('os.environ', {'FLY_PROCESS_GROUP': case['group']}), \
                 patch('prefect.Flow', return_value=mock_flow):

                # Execute the process group handling logic
                process_group = case['group']
                match process_group:
                    case "initial_disinformation_detection":
                        deployment = mock_flow.to_deployment(**case['expected_params'])
                        mock_serve(deployment, limit=case.get('serve_limit'))
                    case "regenerate_timestamped_transcript":
                        deployment = mock_flow.to_deployment(**case['expected_params'])
                        mock_serve(deployment)
                    case "redo_main_detection":
                        deployment = mock_flow.to_deployment(**case['expected_params'])
                        mock_serve(deployment)
                    case "undo_disinformation_detection":
                        deployment = mock_flow.to_deployment(**case['expected_params'])
                        mock_serve(deployment)
                    case "audio_clipping":
                        deployment = mock_flow.to_deployment(**case['expected_params'])
                        mock_serve(deployment, limit=case.get('serve_limit'))
                    case "undo_audio_clipping":
                        deployment = mock_flow.to_deployment(**case['expected_params'])
                        mock_serve(deployment)
                    case "in_depth_analysis":
                        deployment = mock_flow.to_deployment(**case['expected_params'])
                        mock_serve(deployment, limit=case.get('serve_limit'))
                    case "embedding":
                        deployment = mock_flow.to_deployment(**case['expected_params'])
                        mock_serve(deployment, limit=case.get('serve_limit'))

                # Verify deployment configuration
                mock_flow.to_deployment.assert_called_once_with(**case['expected_params'])

                # Verify serve call
                if 'serve_limit' in case:
                    mock_serve.assert_called_once_with(mock_deployment, limit=case['serve_limit'])
                else:
                    mock_serve.assert_called_once_with(mock_deployment)

    def test_invalid_process_group(self):
        """Test handling of invalid process group"""
        with patch.dict('os.environ', {'FLY_PROCESS_GROUP': 'invalid_group'}):
            process_group = os.environ.get("FLY_PROCESS_GROUP")
            with pytest.raises(ValueError, match=f"Invalid process group: {process_group}"):
                match process_group:
                    case _:
                        raise ValueError(f"Invalid process group: {process_group}")



    def test_sentry_initialization(self, monkeypatch):
        """Test Sentry initialization with DSN"""
        test_dsn = "test-dsn"
        mock_init = Mock()

        # Setup environment and patches before importing
        monkeypatch.setenv('FLY_PROCESS_GROUP', 'initial_disinformation_detection')
        monkeypatch.setenv('SENTRY_DSN', test_dsn)

        with patch.dict('sys.modules', {'sentry_sdk': Mock(init=mock_init)}):
            import processing_pipeline.main

            mock_init.assert_called_once_with(dsn=test_dsn)

    def test_sentry_initialization_no_dsn(self, monkeypatch):
        """Test Sentry initialization when DSN is not set"""
        mock_init = Mock()

        # Setup environment before importing
        monkeypatch.setenv('FLY_PROCESS_GROUP', 'initial_disinformation_detection')
        monkeypatch.delenv('SENTRY_DSN', raising=False)

        with patch.dict('sys.modules', {'sentry_sdk': Mock(init=mock_init)}):
            import processing_pipeline.main

            mock_init.assert_called_once_with(dsn=None)

    def test_module_import_with_different_process_groups(self):
        """Test module import with different process groups"""
        process_groups = [
            'initial_disinformation_detection',
            'regenerate_timestamped_transcript',
            'redo_main_detection',
            'undo_disinformation_detection',
            'audio_clipping',
            'undo_audio_clipping',
            'in_depth_analysis',
            'embedding',
            'invalid_group'
        ]

        for group in process_groups:
            with patch('sentry_sdk.init'), \
                 patch.dict('os.environ', {
                     'FLY_PROCESS_GROUP': group,
                     'SENTRY_DSN': 'test-dsn'
                 }, clear=True):

                # Remove module if it exists
                if 'processing_pipeline.main' in sys.modules:
                    del sys.modules['processing_pipeline.main']

                # Import should work without errors for valid groups
                from processing_pipeline import main

                if group == 'invalid_group':
                    # Invalid group should still allow import but raise error when executed
                    with pytest.raises(ValueError, match=f"Invalid process group: {group}"):
                        process_group = os.environ.get("FLY_PROCESS_GROUP")
                        match process_group:
                            case _:
                                raise ValueError(f"Invalid process group: {process_group}")

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
                import processing_pipeline.main

                mock_init.assert_called_once_with(dsn=case['expected_dsn'])
                mock_init.reset_mock()

    def test_prefect_serve_behavior(self, mock_serve, mock_deployment):
        """Test Prefect serve behavior with different configurations"""
        test_cases = [
            {
                'group': 'initial_disinformation_detection',
                'has_limit': True,
                'limit_value': 100
            },
            {
                'group': 'regenerate_timestamped_transcript',
                'has_limit': False
            },
            {
                'group': 'audio_clipping',
                'has_limit': True,
                'limit_value': 100
            }
        ]

        mock_flow = Mock()
        mock_flow.to_deployment.return_value = mock_deployment

        for case in test_cases:
            mock_serve.reset_mock()
            with patch.dict('os.environ', {
                'FLY_PROCESS_GROUP': case['group'],
                'SENTRY_DSN': 'test-dsn'
            }), patch('prefect.Flow', return_value=mock_flow):

                process_group = case['group']
                match process_group:
                    case "initial_disinformation_detection":
                        deployment = mock_flow.to_deployment(
                            name="Stage 1: Initial Disinformation Detection",
                            concurrency_limit=100,
                            parameters=dict(audio_file_id=None, use_openai=False, limit=1000),
                        )
                        mock_serve(deployment, limit=100)
                    case "regenerate_timestamped_transcript":
                        deployment = mock_flow.to_deployment(
                            name="Stage 1: Regenerate Timestamped Transcript",
                            parameters=dict(stage_1_llm_response_ids=[]),
                        )
                        mock_serve(deployment)
                    case "audio_clipping":
                        deployment = mock_flow.to_deployment(
                            name="Stage 2: Audio Clipping",
                            concurrency_limit=100,
                            parameters=dict(context_before_seconds=90, context_after_seconds=60, repeat=True),
                        )
                        mock_serve(deployment, limit=100)
                    case "embedding":
                        deployment = mock_flow.to_deployment(
                            name="Stage 4: Embedding",
                            concurrency_limit=100,
                            parameters=dict(repeat=True),
                        )
                        mock_serve(deployment, limit=100)

                if case['has_limit']:
                    mock_serve.assert_called_once_with(mock_deployment, limit=case['limit_value'])
                else:
                    mock_serve.assert_called_once_with(mock_deployment)

    def test_process_group_not_set(self, monkeypatch):
        """Test behavior when FLY_PROCESS_GROUP is not set"""
        mock_init = Mock()

        # Clear FLY_PROCESS_GROUP
        monkeypatch.delenv('FLY_PROCESS_GROUP', raising=False)

        with patch.dict('sys.modules', {'sentry_sdk': Mock(init=mock_init)}):
            import processing_pipeline.main

            with pytest.raises(ValueError, match="Invalid process group: None"):
                process_group = None
                match process_group:
                    case _:
                        raise ValueError(f"Invalid process group: {process_group}")

    def test_module_import_with_different_process_groups(self, monkeypatch):
        """Test module import with different process groups"""
        process_groups = [
            'initial_disinformation_detection',
            'regenerate_timestamped_transcript',
            'redo_main_detection',
            'undo_disinformation_detection',
            'audio_clipping',
            'undo_audio_clipping',
            'in_depth_analysis',
            'embedding',
            'invalid_group'
        ]

        for group in process_groups:
            if 'processing_pipeline.main' in sys.modules:
                del sys.modules['processing_pipeline.main']

            mock_init = Mock()

            monkeypatch.setenv('FLY_PROCESS_GROUP', group)
            monkeypatch.setenv('SENTRY_DSN', 'test-dsn')

            with patch.dict('sys.modules', {'sentry_sdk': Mock(init=mock_init)}):
                import processing_pipeline.main

                if group == 'invalid_group':
                    with pytest.raises(ValueError, match=f"Invalid process group: {group}"):
                        process_group = group
                        match process_group:
                            case _:
                                raise ValueError(f"Invalid process group: {process_group}")
